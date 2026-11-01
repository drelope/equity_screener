"""One-time verification of a nightly run, meant to be fired by cron after it finishes.

Waits while the pipeline holds its advisory lock (so it never reports on a half-finished
run), then checks the run record, the supporting-loader stages, the freshness series,
lineage stamps, the issuer-terms invariant and the feature/score dates. Writes a markdown
report to ``artifacts/post_nightly/`` and exits non-zero if any check fails.

    python -m scripts.post_nightly_check --run-date 2026-11-02
    python -m scripts.post_nightly_check --run-date 2026-11-02 --remove-cron   # from cron
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from scripts.run_full_etl import BULK_EDGAR_LOADER, PIPELINE_LOCK_KEY, SUPPORTING_LOADERS
from src.crispdm.db import engine, read_df

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "post_nightly"
PASS, FAIL, INFO = "PASS", "FAIL", "INFO"

#: Stages that must have run and succeeded. The dividend stage is the one that broke the
#: 2026-11-01 run (and halted everything after it), so it is named explicitly.
REQUIRED_OK = (
    "scripts.populate_dividend_data",
    "scripts.populate_companyfacts.dividend",
    "scripts.repair_ticker_profile_sec_terms",
    "scripts.build_features",
    "scripts.score_rank",
    "scripts.populate_audit",
)
#: The supporting loaders may be skipped (not due, or no key) but must not be absent or failed.
SUPPORTING_LABELS = tuple(spec["label"] for spec in (BULK_EDGAR_LOADER, *SUPPORTING_LOADERS))

#: Absolute path: the job runs from cron with a minimal PATH.
CRONTAB = "/usr/bin/crontab"

LOCK_SQL = """
SELECT count(*) FROM pg_locks
WHERE locktype = 'advisory' AND granted
  AND ((classid::bigint << 32) | objid::bigint) = :key
"""


def check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def pipeline_running(conn=None) -> bool:
    """True while an ETL run holds the pipeline advisory lock."""
    sql = text(LOCK_SQL)
    if conn is not None:
        return bool(conn.execute(sql, {"key": PIPELINE_LOCK_KEY}).scalar())
    with engine.connect() as c:
        return bool(c.execute(sql, {"key": PIPELINE_LOCK_KEY}).scalar())


def evaluate_run(record: dict | None, run_date: date) -> list[dict]:
    """Checks on the audit.nightly_runs row for ``run_date`` (pure; kept for tests)."""
    if record is None:
        return [
            check(
                "run_recorded",
                FAIL,
                f"no audit.nightly_runs row for {run_date}: the nightly did not run (host asleep "
                "or timer missed) or died before recording",
            )
        ]
    stages = {k: v for k, v in (record.get("stages") or {}).items() if k != "_seconds"}
    out = [
        check(
            "run_recorded",
            PASS,
            f"run {record.get('run_id')} {record.get('trigger')} "
            f"{record.get('started_at')} -> {record.get('finished_at')}",
        )
    ]
    ok = record.get("status") == "success" and record.get("exit_code") == 0
    out.append(
        check(
            "run_status",
            PASS if ok else FAIL,
            f"status={record.get('status')} exit_code={record.get('exit_code')}",
        )
    )
    failed = [k for k, v in stages.items() if v == "failed"]
    out.append(
        check(
            "failed_stages",
            FAIL if failed else PASS,
            ", ".join(failed) if failed else f"none of {len(stages)} stages failed",
        )
    )
    bad = [f"{k}={stages.get(k, 'MISSING')}" for k in REQUIRED_OK if stages.get(k) != "ok"]
    out.append(
        check(
            "required_stages",
            FAIL if bad else PASS,
            ", ".join(bad) if bad else f"all {len(REQUIRED_OK)} required stages ok",
        )
    )
    states = {k: stages.get(k, "MISSING") for k in SUPPORTING_LABELS}
    bad_loaders = [f"{k}={v}" for k, v in states.items() if v not in ("ok", "skipped")]
    summary = ", ".join(f"{k.removeprefix('scripts.')}={v}" for k, v in states.items())
    out.append(
        check(
            "supporting_loaders",
            FAIL if bad_loaders else PASS,
            f"not ok/skipped: {', '.join(bad_loaders)}" if bad_loaders else summary,
        )
    )
    return out


def evaluate_freshness(rows: list[dict]) -> dict:
    """Check the latest audit.source_freshness measurement of every source."""
    if not rows:
        return check("source_freshness", FAIL, "audit.source_freshness_latest is empty")
    breaches = [r for r in rows if r.get("within_sla") is False]
    detail = "; ".join(
        f"{r['source']} {'n/a' if r.get('age_hours') is None else format(float(r['age_hours']), '.1f') + 'h'}"
        f" (SLA {float(r['sla_hours']):.0f}h){' BREACH' if r.get('within_sla') is False else ''}"
        for r in rows
    )
    return check("source_freshness", FAIL if breaches else PASS, detail)


def render_report(run_date: date, results: list[dict], generated_at: datetime) -> str:
    failed = [r for r in results if r["status"] == FAIL]
    lines = [
        f"# Post-nightly check for {run_date}",
        "",
        f"Generated {generated_at.isoformat(timespec='seconds')}. "
        f"**{'ALL CHECKS PASSED' if not failed else f'{len(failed)} CHECK(S) FAILED'}**",
        "",
        "| Status | Check | Detail |",
        "|---|---|---|",
    ]
    for r in results:
        detail = str(r["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['status']} | {r['name']} | {detail} |")
    return "\n".join(lines) + "\n"


def remove_cron_entry(crontab_text: str, marker: str) -> str:
    """The crontab with every line carrying ``marker`` removed."""
    kept = [line for line in crontab_text.splitlines() if marker not in line]
    return "\n".join(kept) + ("\n" if kept else "")


def _remove_cron(marker: str) -> str:
    current = subprocess.run([CRONTAB, "-l"], capture_output=True, text=True)  # noqa: S603 - fixed argument list from constants, never a shell
    if current.returncode != 0:
        return "no crontab to edit"
    updated = remove_cron_entry(current.stdout, marker)
    subprocess.run([CRONTAB, "-"], input=updated, text=True, check=True)  # noqa: S603 - fixed argument list from constants, never a shell
    return "removed its cron entry" if marker in current.stdout else "cron entry already absent"


def wait_for_pipeline(max_wait_minutes: float, poll_seconds: float = 300, sleep=time.sleep) -> str:
    """Block while the pipeline lock is held. Returns what happened, for the report."""
    waited = 0.0
    while pipeline_running():
        if waited >= max_wait_minutes * 60:
            return f"pipeline still running after waiting {max_wait_minutes:.0f} min"
        sleep(poll_seconds)
        waited += poll_seconds
    return f"pipeline idle (waited {waited / 60:.0f} min)" if waited else "pipeline already idle"


def _record_for(run_date: date) -> dict | None:
    frame = read_df(
        "SELECT run_id, run_date, trigger, started_at, finished_at, status, exit_code, stages "
        "FROM audit.nightly_runs WHERE run_date = :d ORDER BY started_at DESC LIMIT 1",
        {"d": run_date},
    )
    return None if frame.empty else frame.iloc[0].to_dict()


def _verify(run_date: date) -> list[dict]:
    """The standard morning verification, recorded in audit.nightly_checks."""
    proc = subprocess.run(  # noqa: S603 - fixed argument list from constants, never a shell
        [
            sys.executable,
            "-m",
            "scripts.verify_nightly_run",
            "--run-date",
            run_date.isoformat(),
            "--json",
            "--verified-by",
            "post-nightly-check",
        ],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    start = proc.stdout.find("{")
    if start < 0:
        return [check("verify_nightly_run", FAIL, f"no JSON output: {proc.stderr.strip()[-300:]}")]
    payload = json.loads(proc.stdout[start:])
    out = [
        check("verify_nightly_run", PASS if payload["status"] == "ok" else FAIL, payload["status"])
    ]
    for c in payload["checks"]:
        if c["status"] == "attention":
            out.append(check(f"verify:{c['name']}", FAIL, c["detail"]))
    return out


def _issuer_terms_test() -> dict:
    proc = subprocess.run(  # noqa: S603 - fixed argument list from constants, never a shell
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_issuer_terms_view.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    tail = (
        proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr.strip()[-200:]
    )
    return check("issuer_terms_invariant", PASS if proc.returncode == 0 else FAIL, tail)


def _data_checks() -> list[dict]:
    out = []
    gaps = int(
        read_df(
            "SELECT count(*) FROM audit.source_lineage "
            "WHERE source IS NULL OR model_version IS NULL OR feature_set_hash IS NULL"
        ).iloc[0, 0]
    )
    out.append(
        check("lineage_stamps", FAIL if gaps else PASS, f"{gaps} lineage rows missing a stamp")
    )
    dates = read_df(
        "SELECT (SELECT max(as_of_date) FROM model.features) AS features, "
        "(SELECT max(as_of_date) FROM model.scores) AS scores, "
        "(SELECT max(as_of_date) FROM model.predictions) AS predictions"
    ).iloc[0]
    out.append(
        check(
            "latest_model_dates",
            INFO,
            f"features {dates.features}, scores {dates.scores}, predictions {dates.predictions}",
        )
    )
    fresh = read_df(
        "SELECT (SELECT max(retrieved_at) FROM raw.corporate_actions) AS corporate_actions, "
        "(SELECT max(retrieved_at) FROM raw.dividend_calendar) AS dividend_calendar, "
        "(SELECT max(retrieved_at) FROM raw.sec_submissions) AS sec_submissions, "
        "(SELECT count(*) FROM raw.dividend_data WHERE is_special) AS special_dividends"
    ).iloc[0]
    out.append(check("loader_activity", INFO, "; ".join(f"{k}={v}" for k, v in fresh.items())))
    return out


def run(run_date: date, max_wait_minutes: float) -> list[dict]:
    results = [check("pipeline_state", INFO, wait_for_pipeline(max_wait_minutes))]
    if pipeline_running():
        results.append(
            check("run_recorded", FAIL, "the nightly was still running; no verdict possible")
        )
        return results
    results += evaluate_run(_record_for(run_date), run_date)
    results += _verify(run_date)
    latest = read_df("SELECT * FROM audit.source_freshness_latest ORDER BY source")
    results.append(evaluate_freshness(latest.to_dict("records")))
    results += _data_checks()
    results.append(_issuer_terms_test())
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", type=date.fromisoformat, required=True)
    parser.add_argument("--max-wait-minutes", type=float, default=360.0)
    parser.add_argument(
        "--remove-cron", action="store_true", help="Delete this job's cron entry when done."
    )
    args = parser.parse_args()
    results = run(args.run_date, args.max_wait_minutes)
    report = render_report(args.run_date, results, datetime.now(timezone.utc))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f"report_{args.run_date}.md").write_text(report, encoding="utf-8")
    (OUTPUT_DIR / "latest.md").write_text(report, encoding="utf-8")
    print(report)
    if args.remove_cron:
        print(_remove_cron(f"post-nightly-check-{args.run_date}"))
    return 1 if any(r["status"] == FAIL for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
