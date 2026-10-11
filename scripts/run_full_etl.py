"""
Run the full dividend-equity ETL pipeline.

Stages (in dependency order):
    0. populate_raw_tables       -> raw.company_ticker + raw.ticker_profile (dividend payers)
    1. populate_reference_tables -> reference.exchanges/issuers/securities (dividend flags)
    2. populate_market_data      -> raw.market_data daily OHLCV (dividend universe only)
    3. populate_dividend_data    -> raw.dividend_data, raw.ticker_profile, preferred.security_terms
    3a. populate_clean_ticker_profile -> clean.ticker_profile (one normalized CIK/ticker row)
    3b. populate_clean_company_profile -> clean.company_profile + clean.company_officer
                                         + clean.corporate_action
    4a. ... --preferred-facts   -> raw.companyfacts (preferred set; priority, runs first)
    4b. populate_companyfacts   -> raw.sec_submissions + raw.companyfacts (dividend universe)
    4c. ... --sweep-unlinked    -> raw.companyfacts (CIKs in neither universe)
    5. populate_sec_documents    -> raw.sec_documents concept_groups (dividend universe only)
    6. populate_fundamentals     -> fundamentals.periodic_financials (offline, stored XBRL)
    7. build_features            -> model.features (offline, last --feature-days only)
    8. score_rank                -> model.scores + model.predictions + model.rankings
    9. populate_audit            -> audit.source_lineage + audit.data_quality (offline)
    10. label_targets (optional) -> model.features.target_sustainable_dividend
                                    (run with --run-labels after ~12 months of data)

Before stage 0, ``migrate --check`` refuses to start if any migration on disk
is unapplied. Stages 6-8 were not wired in until the 2026-09-30 session: the
nightly refreshed prices and dividends but nothing downstream, which is why
model.scores was empty and the dashboard's Median Score read N/A. Stage 7 is
incremental -- the feature insert upserts on (security_id, as_of_date) and only
the last ``--feature-days`` observations are rebuilt, which must exceed the 252
trading-day price lookback behind the volatility and momentum features.

Stages 2-5 only touch securities flagged ``dividend = TRUE`` in
``reference.securities``, so SEC and OpenBB are never called for non-payers.
Stages 4a/4b re-fetch stored SEC companyfacts payloads once they are older than
``--companyfacts-refresh-after-days`` (default 5): a stored CIK is otherwise
skipped forever, which would freeze the filings and every point-in-time vintage
derived from them at first sighting.
Stages 6-9 need no network at all and run over whatever is already stored.
Stage 10 (labels) is refused on ``--limit``/``--tickers`` runs because labels
are immutable once written; a partial run would freeze wrong labels.

Every run is recorded in ``audit.nightly_runs`` (per-stage results, exit code,
trigger) so ``scripts.verify_nightly_run`` can audit it next morning. Recording
failure never fails the ETL; verify then flags the missing record.

Usage:
    python -m scripts.run_full_etl
    python -m scripts.run_full_etl --limit 50
    python -m scripts.run_full_etl --tickers ACR-PC,ACR-PD
    python -m scripts.run_full_etl --skip-companyfacts --skip-sec-documents
    python -m scripts.run_full_etl --skip-derived
    python -m scripts.run_full_etl --run-labels --label-cutoff 2026-12-31
    python -m scripts.run_full_etl --dividend-full-history   # post-PoC total history
    python -m scripts.run_full_etl --trigger systemd          # set by scheduler
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from src.crispdm.db import engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_module(name, args, skip=False):
    if skip:
        print(f"[skip] {name}")
        return True
    print(f"\n=== {name} ===")
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", name, *args],
        cwd=PROJECT_ROOT,
    )
    elapsed = time.monotonic() - started
    print(f"=== {name} finished in {elapsed:.1f}s (exit {result.returncode}) ===")
    return result.returncode == 0


_ROW_COUNT_QUERIES = {
    "securities_total": "SELECT count(*) FROM reference.securities",
    "securities_active": "SELECT count(*) FROM reference.securities WHERE active",
    "dividend_payers_active": (
        "SELECT count(*) FROM reference.securities WHERE active AND dividend"
    ),
    "active_duplicate_cik_ticker": (
        "SELECT count(*) FROM (SELECT 1 FROM reference.securities WHERE active "
        "GROUP BY cik, ticker HAVING count(*) > 1) d"
    ),
    "features_latest": (
        "SELECT count(*) FROM model.features "
        "WHERE as_of_date = (SELECT max(as_of_date) FROM model.features)"
    ),
    "predictions_latest": (
        "SELECT count(*) FROM model.predictions "
        "WHERE as_of_date = (SELECT max(as_of_date) FROM model.predictions)"
    ),
    "preferred_terms": "SELECT count(*) FROM preferred.security_terms",
}


def collect_row_counts():
    """Snapshot universe sizes for churn tracking; empty dict if unavailable."""
    counts = {}
    try:
        with engine.connect() as c:
            for key, sql in _ROW_COUNT_QUERIES.items():
                counts[key] = int(c.execute(text(sql)).scalar() or 0)
    except Exception as exc:
        print(f"[run_full_etl] could not collect row counts: {exc}", file=sys.stderr)
    return counts


def record_nightly_run(trigger, started_at, stages, exit_code):
    """Write the run into audit.nightly_runs; never fail the ETL on recording."""
    try:
        status = "success" if exit_code == 0 else "failed"
        finished = datetime.now(timezone.utc)
        row_counts = collect_row_counts()
        with engine.begin() as c:
            c.execute(
                text(
                    """
                    INSERT INTO audit.nightly_runs
                      (run_date, trigger, started_at, finished_at, exit_code, stages, status,
                       row_counts)
                    VALUES (:run_date, :trigger, :started_at, :finished_at,
                            :exit_code, :stages, :status, CAST(:row_counts AS jsonb))
                    """
                ),
                {
                    "run_date": date.today(),
                    "trigger": trigger,
                    "started_at": started_at,
                    "finished_at": finished,
                    "exit_code": exit_code,
                    "stages": json.dumps(stages, default=str),
                    "status": status,
                    "row_counts": json.dumps(row_counts),
                },
            )
    except Exception as exc:
        print(f"[run_full_etl] could not record audit.nightly_runs: {exc}", file=sys.stderr)


#: Arbitrary but fixed key for the pipeline's mutual-exclusion lock. Postgres
#: advisory locks are cluster-wide, so the same value excludes a manual run, a
#: second systemd invocation, and a developer's foreground run alike.
PIPELINE_LOCK_KEY = 4_713_155_001


class PipelineAlreadyRunning(RuntimeError):
    """Another ETL run is in flight against the same warehouse."""


def _acquire_run_lock():
    """Take the pipeline lock on a dedicated connection, or raise.

    Returned handle must be passed to :func:`_release_run_lock`. Advisory locks
    are session-scoped, so this deliberately holds its own connection open for
    the life of the run rather than borrowing a per-call one.

    This is the overlap that actually happened: a hand-started
    populate_dividend_data was still running 1h33m into the first timer-driven
    nightly, putting two writers on the same tables. systemd will not start a
    second instance of a unit it already has active, so the timer alone cannot
    cause it -- the exposure is a manual or foreground run.
    """
    conn = engine.connect()
    acquired = conn.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": PIPELINE_LOCK_KEY}
    ).scalar()
    if not acquired:
        conn.close()
        raise PipelineAlreadyRunning(
            "another ETL run holds the pipeline lock; refusing to run a second one "
            "against the same warehouse. Wait for it to finish, or inspect "
            "`pg_locks WHERE locktype = 'advisory'`."
        )
    return conn


def _release_run_lock(conn):
    """Release the lock and close its connection; safe to call once per run."""
    if conn is None:
        return
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": PIPELINE_LOCK_KEY})
        conn.commit()
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit reference/dividend/companyfacts ingestion to first N (testing)",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated tickers; restricted to dividend payers unless --all",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="all",
        choices=["all", "sec", "openbb"],
        help="Sources for the dividend-data stage",
    )
    parser.add_argument("--skip-reference", action="store_true", help="Skip stage 1")
    parser.add_argument("--skip-raw", action="store_true", help="Skip stage 0")
    parser.add_argument("--skip-market-data", action="store_true", help="Skip stage 2")
    parser.add_argument("--skip-dividend-data", action="store_true", help="Skip stage 3")
    parser.add_argument("--skip-companyfacts", action="store_true", help="Skip stage 4b")
    parser.add_argument(
        "--companyfacts-refresh-after-days",
        type=int,
        default=5,
        help="Stages 4b/4c re-fetch a stored SEC companyfacts payload once it is older "
        "than this many days (default 5). A stored CIK is otherwise skipped forever, "
        "which freezes the filings -- and every point-in-time vintage derived from "
        "them -- at first sighting. Use 0 to re-fetch on every run, or a negative "
        "value to never re-fetch. The default is 5 and not 7 because the freshness "
        "check bounds this table at 8 days: a 7-day cadence leaves one day of "
        "slack, so a single missed nightly -- one laptop lid closed at 03:00 -- "
        "breaches the source. 5 against 8 tolerates two.",
    )
    parser.add_argument(
        "--preferred-companyfacts-refresh-after-days",
        type=int,
        default=3,
        help="Stage 4a re-fetches a stored SEC companyfacts payload for the PREFERRED "
        "set once it is older than this many days (default 3). This half of "
        "raw.companyfacts is the priority: it runs first and on the tighter "
        "cadence, so an interrupted or timed-out nightly still leaves it the "
        "freshest. Same 0 / negative conventions as the dividend universe.",
    )
    parser.add_argument(
        "--skip-preferred-companyfacts",
        action="store_true",
        help="Skip stage 4a. Only safe if the preferred-set companyfacts payloads are "
        "not expected to change: the freshness check ages raw.companyfacts by its "
        "oldest row, so leaving these un-refreshed fails the bound for the whole "
        "source.",
    )
    parser.add_argument(
        "--skip-unlinked-companyfacts",
        action="store_true",
        help="Skip stage 4c. Only safe if the stored companyfacts rows that belong to "
        "neither the dividend nor the preferred universe are not expected to change: "
        "the freshness check ages raw.companyfacts by its oldest row, so leaving "
        "them un-refreshed fails the bound for the whole source.",
    )
    parser.add_argument("--skip-sec-documents", action="store_true", help="Skip stage 5")
    parser.add_argument(
        "--skip-derived",
        action="store_true",
        help="Do not run the offline derived stages (fundamentals, features, "
        "scoring, audit) or the schema preflight",
    )
    parser.add_argument(
        "--feature-days",
        type=int,
        default=400,
        help="Days of observations for the nightly feature rebuild (default: 400). "
        "Must exceed the longest price lookback (252 trading days) or the "
        "volatility and momentum features lose their trailing window.",
    )
    parser.add_argument(
        "--skip-profiles", action="store_true", help="Do not refresh raw.ticker_profile in stage 3"
    )
    parser.add_argument(
        "--run-labels",
        action="store_true",
        help="Stage 8: populate target_sustainable_dividend from future dividend "
        "events (default off; refused on partial runs)",
    )
    parser.add_argument(
        "--label-cutoff",
        type=date.fromisoformat,
        default=None,
        help="Label horizon cutoff for stage 8 (default: today)",
    )
    parser.add_argument(
        "--price-start",
        type=str,
        default=None,
        help="Override the price lookback start for stage 2 "
        "(default: PRICE_LOOKBACK_START, i.e. 2023-09-01)",
    )
    parser.add_argument(
        "--dividend-start",
        type=str,
        default=None,
        help="Override the 12-month dividend lookback start for stage 3 "
        "(default: DIVIDEND_LOOKBACK_START, i.e. 2025-01-01)",
    )
    parser.add_argument(
        "--dividend-full-history",
        action="store_true",
        help="Post-PoC provision: stage 3 fetches the full available dividend "
        "history instead of the 12-month lookback",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include non-dividend securities in stages 2-5 (not recommended)",
    )
    parser.add_argument(
        "--trigger",
        type=str,
        default="manual",
        choices=["manual", "airflow", "systemd"],
        help="How this run was started (recorded in audit.nightly_runs)",
    )
    args = parser.parse_args()

    if args.run_labels and (args.limit is not None or args.tickers):
        print(
            "[run_full_etl] refusing --run-labels on a partial run "
            "(--limit/--tickers): labels are immutable once written, so a "
            "partial run would freeze wrong labels. Run the full universe, "
            "or repair later with scripts.label_targets --rebuild."
        )
        return 1

    base = []
    if args.tickers:
        base += ["--tickers", args.tickers]

    raw_args = ["--limit", str(args.limit)] if args.limit is not None else []
    reference_args = ["--limit", str(args.limit)] if args.limit is not None else []
    market_data_args = list(base)
    if args.limit is not None:
        market_data_args += ["--limit", str(args.limit)]
    if args.price_start is not None:
        market_data_args += ["--start-date", args.price_start]
    dividend_args = list(base)
    if args.limit is not None:
        dividend_args += ["--limit", str(args.limit)]
    companyfacts_args = list(base)
    if args.companyfacts_refresh_after_days >= 0:
        companyfacts_args += ["--refresh-after-days", str(args.companyfacts_refresh_after_days)]
    if args.limit is not None:
        companyfacts_args += ["--max-ciks", str(args.limit)]
    preferred_companyfacts_args = list(base) + ["--preferred-facts"]
    if args.preferred_companyfacts_refresh_after_days >= 0:
        preferred_companyfacts_args += [
            "--refresh-after-days",
            str(args.preferred_companyfacts_refresh_after_days),
        ]
    if args.limit is not None:
        preferred_companyfacts_args += ["--max-ciks", str(args.limit)]
    unlinked_companyfacts_args = list(base) + ["--sweep-unlinked"]
    if args.companyfacts_refresh_after_days >= 0:
        unlinked_companyfacts_args += [
            "--refresh-after-days",
            str(args.companyfacts_refresh_after_days),
        ]
    if args.limit is not None:
        unlinked_companyfacts_args += ["--max-ciks", str(args.limit)]
    sec_documents_args = list(base)

    started_at = datetime.now(timezone.utc)
    stages = {}
    # Per-stage wall time, attached to the stages record under a reserved key
    # just before it is written: the journal does not survive a reboot (the
    # Oct 6 power cycle erased three healthy runs' stage timings),
    # audit.nightly_runs does. Consumers compare status values with ==, which a
    # dict never equals, and the key is attached last so insertion order still
    # reads as the order the stages ran.
    stage_seconds = {}
    all_ok = True

    try:
        lock_conn = _acquire_run_lock()
    except PipelineAlreadyRunning as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        return 2

    try:

        def stage(module, extra, skip=False, label=None):
            """Run one stage.

            ``module`` is what gets handed to ``python -m``; ``label`` is what goes
            into the audit record. They differ wherever one script covers several
            populations via a flag, since ``scripts.populate_companyfacts`` has no
            submodule named ``preferred`` or ``unlinked`` -- and a dotted pseudo-module
            fails at runtime with ModuleNotFoundError. Keeping them separate means the
            audit row can still distinguish the populations while the subprocess
            always names a module that actually exists.
            """
            stage_started = time.monotonic()
            ok = run_module(module, extra, skip=skip)
            key = label or module
            stages[key] = "skipped" if skip else ("ok" if ok else "failed")
            stage_seconds[key] = round(time.monotonic() - stage_started, 1)
            return ok

        # Preflight, before any long stage. A stage that reads a column the
        # database does not have fails at execution -- hours in, with the rows it
        # did manage to write already committed. This is what let the 02:00
        # nightly write nothing and still be recorded as successful.
        if not stage(
            "scripts.migrate", ["--check"], args.skip_derived, label="scripts.migrate --check"
        ):
            all_ok = False

        if all_ok and not stage("scripts.populate_raw_tables", raw_args, args.skip_raw):
            all_ok = False

        if all_ok and not stage(
            "scripts.populate_reference_tables", reference_args, args.skip_reference
        ):
            all_ok = False

        if all_ok:
            if args.all:
                market_data_args += ["--all"]
        if not stage("scripts.populate_market_data", market_data_args, args.skip_market_data):
            all_ok = False

        if all_ok:
            if args.sources != "all":
                dividend_args += ["--sources", args.sources]
            if args.dividend_full_history:
                dividend_args += ["--full-history"]
            elif args.dividend_start is not None:
                dividend_args += ["--start-date", args.dividend_start]
            if args.skip_profiles:
                dividend_args += ["--skip-profiles"]
            if args.all:
                dividend_args += ["--include-non-dividend"]
        if all_ok and not stage(
            "scripts.populate_dividend_data", dividend_args, args.skip_dividend_data
        ):
            all_ok = False

        if all_ok and not stage("scripts.populate_clean_ticker_profile", []):
            all_ok = False

        if all_ok and not stage("scripts.populate_clean_company_profile", []):
            all_ok = False

        # raw.companyfacts holds three populations, all refreshed here.
        #
        # Stage 4a is the preferred set and runs FIRST: it is the priority half, on a
        # tighter cadence (3 days against 7), so a nightly that is cut short -- by the
        # 12h TimeoutStartSec, or by a WSL2 host that suspends mid-run -- still leaves
        # the preferred payloads fresh rather than frozen at first sighting. 4b then
        # sweeps the dividend universe, and 4c the CIKs in neither universe.
        #
        # All three are required, not alternatives: the freshness check ages this table
        # by its OLDEST row, so one never-refreshed CIK fails the bound for the whole
        # source. Priority is about ordering and cadence, not about which populations
        # may be skipped -- hence a --skip-* flag per stage, each documenting the
        # consequence. The overlap costs nothing: a CIK 4a just refreshed is not yet
        # due, so 4b and 4c skip it.
        if all_ok and not stage(
            "scripts.populate_companyfacts",
            preferred_companyfacts_args,
            args.skip_preferred_companyfacts,
            label="scripts.populate_companyfacts.preferred",
        ):
            all_ok = False

        if all_ok:
            if args.all:
                companyfacts_args += ["--all"]
        if all_ok and not stage(
            "scripts.populate_companyfacts",
            companyfacts_args,
            args.skip_companyfacts,
            label="scripts.populate_companyfacts.dividend",
        ):
            all_ok = False

        # raw.companyfacts has a third population: CIKs stored by an earlier, wider
        # run that are in neither the dividend nor the preferred universe (2,896 rows
        # here). Both sweeps walk a security universe, so those rows are invisible to
        # both, and the MIN-based freshness check would pin the whole source to a
        # permanent breach on rows no stage log mentions. Runs last: it is the
        # lowest-priority population and shares the dividend cadence.
        if all_ok and not stage(
            "scripts.populate_companyfacts",
            unlinked_companyfacts_args,
            args.skip_unlinked_companyfacts,
            label="scripts.populate_companyfacts.unlinked",
        ):
            all_ok = False

        if all_ok:
            if args.all:
                sec_documents_args += ["--all"]
        if all_ok and not stage(
            "scripts.populate_sec_documents", sec_documents_args, args.skip_sec_documents
        ):
            all_ok = False

        if all_ok and not stage("scripts.populate_fundamentals", [], args.skip_derived):
            all_ok = False

        # Features and scoring were not stages until now, which is why
        # model.scores was empty and the dashboard's Median Score read N/A: the
        # nightly refreshed prices and dividends but nothing downstream of them.
        # Both are incremental -- the feature insert upserts on
        # (security_id, as_of_date) and only the recent tail is rebuilt, and
        # score_rank scores the latest date -- so the added cost is minutes, not
        # the ~50 minutes a full history rebuild takes.
        if all_ok and not stage(
            "scripts.build_features", ["--days", str(args.feature_days)], args.skip_derived
        ):
            all_ok = False

        # --prune-superseded drops predictions of superseded runs at the scored
        # date; without it a features mid-rebuild leaves a mixed-date view that
        # no later nightly touches again (its prune only ever sees the newest
        # date). Retention of older dates is unaffected.
        if all_ok and not stage("scripts.score_rank", ["--prune-superseded"], args.skip_derived):
            all_ok = False

        # The audit snapshot runs last so it records the scores just written.
        if all_ok and not stage("scripts.populate_audit", [], args.skip_derived):
            all_ok = False

        if all_ok and args.run_labels:
            label_args = ["--cutoff", args.label_cutoff.isoformat()] if args.label_cutoff else []
            if not stage("scripts.label_targets", label_args):
                all_ok = False

        exit_code = 0 if all_ok else 1
        stages["_seconds"] = stage_seconds
        record_nightly_run(args.trigger, started_at, stages, exit_code)

        if all_ok:
            print("\nFull ETL pipeline complete.")
        return exit_code
    finally:
        _release_run_lock(lock_conn)


if __name__ == "__main__":
    sys.exit(main())
