"""
Single-owner nightly verification: did the ETL run, and are the data modules healthy?

The single owner runs this each morning after the 03:00 ET nightly ETL. It
checks, for the target run date:

  1. **Nightly run** — an ``audit.nightly_runs`` row exists for ``run_date``
     with status ``success`` (exit 0) and no failed stages.
  2. **Data-module audit freshness** — ``audit.data_quality`` has the run-date
     score; the newest SEC/OpenBB retrievals and dividend events are within the
     freshness SLA (default 26 hours).
  3. **Dividend accrual** — share of the ``dividend = TRUE`` universe covered by
     ``raw.dividend_data`` rows in the lookback window (default 2025-01-01)
     meets the coverage threshold.
  4. **Data quality** — share of securities rated good/fair and the mean
     completeness meet thresholds.
  5. **Walk-forward gate** — the latest ``audit.model_runs`` recall clears
     ``MIN_RECALL``. Informational until real data accrues (no rows yet).

Every verification is recorded in ``audit.nightly_checks`` (the auditable trail;
the SDLC review's PM Go/No-Go record). Table creation: ``scripts.migrate``
(applies sql/migrations/V0005_nightly_run_tracking.sql).

Exit codes: 0 = all checks pass; 1 = attention needed (a critical check failed).

Usage:
    python -m scripts.verify_nightly_run
    python -m scripts.verify_nightly_run --run-date 2026-09-24
    python -m scripts.verify_nightly_run --json
    python -m scripts.verify_nightly_run --no-check-log
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from src.crispdm.config import settings
from src.crispdm.db import engine

ET = ZoneInfo("America/New_York")
CHECK_TABLES_MISSING = (
    "run-tracking tables not found (apply python -m scripts.migrate, "
    "V0005_nightly_run_tracking.sql)"
)


def target_run_date(now_utc=None):
    """The ET calendar date the 03:00 ET nightly run would cover."""
    et = (now_utc or datetime.now(timezone.utc)).astimezone(ET)
    if et.hour >= 3:
        return et.date()
    return (et - timedelta(days=1)).date()


def _check(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def assess(findings, *, min_quality_score, min_good_share, min_coverage, max_age_hours):
    """Turn DB findings into check statuses (pure; kept for tests)."""
    checks = []

    run = findings.get("nightly_run")
    if run is None:
        checks.append(_check("nightly_run_record", "attention", "no audit.nightly_runs row"))
        stage_failed = None
    else:
        run_ok = run.get("status") == "success" and run.get("exit_code") == 0
        stage_failed = [name for name, st in (run.get("stages") or {}).items() if st == "failed"]
        checks.append(
            _check(
                "nightly_run_record",
                "ok" if run_ok else "attention",
                f"{run.get('trigger', '?')} run {run.get('run_date')} "
                f"status={run.get('status')} exit={run.get('exit_code')} "
                f"({len(run.get('stages') or {})} stages, failed={stage_failed or 'none'})",
            )
        )

    if stage_failed:
        checks.append(_check("stages", "attention", f"failed stages: {', '.join(stage_failed)}"))

    freshness = findings.get("freshness")
    if freshness is None:
        checks.append(_check("freshness", "attention", CHECK_TABLES_MISSING))
    else:
        worst = max(
            age
            for age in [
                freshness.get("max_retrieval_age_hours"),
                freshness.get("dividend_ex_age_hours"),
            ]
            if age is not None
        )
        checks.append(
            _check(
                "freshness",
                "ok" if worst <= max_age_hours else "attention",
                f"oldest critical source {worst:.1f}h old (SLA {max_age_hours}h)",
            )
        )

    quality = findings.get("quality")
    if quality is None:
        checks.append(_check("data_quality", "attention", CHECK_TABLES_MISSING))
    else:
        share_good = quality.get("good_fair_share", 0.0)
        score = quality.get("mean_quality_score", 0.0)
        checks.append(
            _check(
                "data_quality",
                "ok"
                if score >= min_quality_score and share_good >= min_good_share
                else "attention",
                f"mean quality {score:.2f} (min {min_quality_score}), "
                f"good/fair share {share_good:.0%} (min {min_good_share:.0%}), "
                f"n={quality.get('n', 0)}",
            )
        )

    coverage = findings.get("coverage")
    if coverage is None:
        checks.append(_check("dividend_coverage", "attention", CHECK_TABLES_MISSING))
    else:
        covered = coverage.get("covered", 0)
        universe = coverage.get("universe")
        share = covered / universe if universe else 0.0
        checks.append(
            _check(
                "dividend_coverage",
                "ok" if universe and share >= min_coverage else "attention",
                f"{covered}/{universe} dividend securities covered in lookback "
                f"({share:.0%}, min {min_coverage:.0%})",
            )
        )

    model = findings.get("model_gate")
    if model is None:
        checks.append(_check("walk_forward_gate", "attention", CHECK_TABLES_MISSING))
    elif model.get("run_id") is None:
        checks.append(
            _check(
                "walk_forward_gate",
                "info",
                "no model_runs yet; gate pending real-data accrual",
            )
        )
    else:
        ok = model.get("recall") is not None and model.get("recall") >= settings.min_recall
        checks.append(
            _check(
                "walk_forward_gate",
                "ok" if ok else "attention",
                f"recall={model.get('recall'):.3f} vs MIN_RECALL={settings.min_recall:.2f} "
                f"({model.get('created_at')})",
            )
        )

    status = "ok" if not any(c["status"] == "attention" for c in checks) else "attention"
    return {"status": status, "run_date": findings.get("run_date"), "checks": checks}


def fetch_findings(conn, run_date, lookback_start):
    findings = {"run_date": run_date.isoformat(), "nightly_run": None, "model_gate": None}

    try:
        run = (
            conn.execute(
                text(
                    """
                SELECT run_date, trigger, started_at, finished_at, exit_code, stages, status
                FROM audit.nightly_runs
                WHERE run_date = :run_date
                ORDER BY started_at DESC
                LIMIT 1
                """
                ),
                {"run_date": run_date},
            )
            .mappings()
            .first()
        )
        findings["nightly_run"] = dict(run) if run else None

        quality = (
            conn.execute(
                text(
                    """
                SELECT COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE status IN ('good', 'fair')) AS good_fair,
                       COALESCE(AVG(quality_score), 0.0) AS mean_score
                FROM audit.data_quality
                WHERE as_of_date = :run_date
                """
                ),
                {"run_date": run_date},
            )
            .mappings()
            .first()
        )
        findings["quality"] = {
            "n": quality["n"],
            "good_fair": quality["good_fair"],
            "good_fair_share": (quality["good_fair"] / quality["n"] if quality["n"] else 0.0),
            "mean_quality_score": float(quality["mean_score"]),
        }

        cov = (
            conn.execute(
                text(
                    """
                SELECT
                  (SELECT COUNT(*) FROM reference.securities WHERE dividend = TRUE) AS universe,
                  (SELECT COUNT(DISTINCT d.security_id)
                   FROM raw.dividend_data d
                   JOIN reference.securities s ON s.security_id = d.security_id
                   WHERE s.dividend = TRUE AND d.ex_dividend_date >= :lookback) AS covered
                """
                ),
                {"lookback": lookback_start},
            )
            .mappings()
            .first()
        )
        findings["coverage"] = {"universe": cov["universe"], "covered": cov["covered"]}

        model = (
            conn.execute(
                text(
                    """
                SELECT run_id, recall, created_at
                FROM audit.model_runs
                ORDER BY created_at DESC
                LIMIT 1
                """
                )
            )
            .mappings()
            .first()
        )
        findings["model_gate"] = {
            "run_id": str(model["run_id"]) if model else None,
            "recall": float(model["recall"]) if model and model["recall"] is not None else None,
            "created_at": (
                model["created_at"].isoformat()
                if model and model["created_at"] is not None
                else None
            ),
        }

        try:
            ages = (
                conn.execute(
                    text(
                        """
                    SELECT
                      (SELECT MAX(retrieved_at) FROM raw.ticker_profile) AS latest_profile,
                      (SELECT MAX(retrieved_at) FROM raw.companyfacts) AS latest_facts,
                      (SELECT MAX(ex_dividend_date) FROM raw.dividend_data) AS latest_ex,
                      (SELECT MAX(updated_at) FROM reference.securities) AS latest_securities
                    """
                    )
                )
                .mappings()
                .first()
            )
            now = datetime.now(timezone.utc)
            findings["freshness"] = {
                "max_retrieval_age_hours": _age_hours(
                    max(
                        ages["latest_profile"],
                        ages["latest_facts"],
                        ages["latest_securities"],
                    ),
                    now,
                ),
                "dividend_ex_age_hours": _age_hours(ages["latest_ex"], now),
            }
        except ProgrammingError:
            findings["freshness"] = None
    except ProgrammingError:
        findings["quality"], findings["coverage"], findings["model_gate"] = None, None, None
        findings["source_lineage_missing"] = True
    return findings


def _age_hours(value, now):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return max(0.0, (now - value).total_seconds() / 3600.0)


def record_check(conn, run_date, status, findings, verified_by, notes):
    conn.execute(
        text(
            """
            INSERT INTO audit.nightly_checks
              (run_date, verified_by, status, findings, notes)
            VALUES (:run_date, :verified_by, :status, :findings, :notes)
            """
        ),
        {
            "run_date": run_date,
            "verified_by": verified_by,
            "status": status,
            "findings": json.dumps(findings, default=str),
            "notes": notes,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-date",
        type=date.fromisoformat,
        default=None,
        help="Run date to verify (default: the ET date the last nightly covered)",
    )
    parser.add_argument(
        "--min-quality-score", type=float, default=0.50, help="Mean quality_score floor"
    )
    parser.add_argument(
        "--min-good-share", type=float, default=0.80, help="Min share rated good/fair"
    )
    parser.add_argument(
        "--min-coverage", type=float, default=0.95, help="Min dividend-universe coverage"
    )
    parser.add_argument(
        "--max-age-hours", type=float, default=26.0, help="Freshness SLA for source retrievals"
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of the table")
    parser.add_argument(
        "--no-check-log",
        action="store_true",
        help="Do not record the verification in audit.nightly_checks",
    )
    parser.add_argument(
        "--verified-by", type=str, default="single-owner", help="Owner identity for the log"
    )
    parser.add_argument("--notes", type=str, default=None, help="Free-text note for the log")
    args = parser.parse_args()

    run_date = args.run_date or target_run_date()
    lookback_start = settings.dividend_lookback_start
    with engine.connect() as conn:
        try:
            findings = fetch_findings(conn, run_date, lookback_start)
        except ProgrammingError:
            findings = {
                "run_date": run_date.isoformat(),
                "nightly_run": None,
                "quality": None,
                "coverage": None,
                "model_gate": None,
                "freshness": None,
            }

        result = assess(
            findings,
            min_quality_score=args.min_quality_score,
            min_good_share=args.min_good_share,
            min_coverage=args.min_coverage,
            max_age_hours=args.max_age_hours,
        )
        result["thresholds"] = {
            "min_quality_score": args.min_quality_score,
            "min_good_share": args.min_good_share,
            "min_coverage": args.min_coverage,
            "max_age_hours": args.max_age_hours,
        }

        if not args.no_check_log:
            try:
                with engine.begin() as conn:
                    record_check(
                        conn,
                        run_date,
                        result["status"],
                        result,
                        args.verified_by,
                        args.notes,
                    )
            except ProgrammingError as exc:
                print(
                    f"[verify] could not record audit.nightly_checks: {exc}",
                    file=sys.stderr,
                )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Nightly verification for {run_date} -> {result['status'].upper()}")
        for check in result["checks"]:
            mark = {"ok": "[ OK ]", "attention": "[ !! ]", "info": "[info]"}[check["status"]]
            print(f"{mark} {check['name']}: {check['detail']}")

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
