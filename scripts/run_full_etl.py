"""
Run the full dividend-equity ETL pipeline.

Stages (in dependency order):
    0. populate_raw_tables       -> raw.company_ticker + raw.ticker_profile (dividend payers)
    1. populate_reference_tables -> reference.exchanges/issuers/securities (dividend flags)
    2. populate_dividend_data    -> raw.dividend_data, raw.ticker_profile, preferred.security_terms
    3. populate_companyfacts     -> raw.sec_submissions + raw.companyfacts (dividend universe only)
    4. populate_sec_documents    -> raw.sec_documents concept_groups (dividend universe only)
5. populate_fundamentals     -> fundamentals.periodic_financials (offline, stored XBRL)
     6. populate_audit            -> audit.source_lineage + audit.data_quality (offline)
     7. label_targets (optional)  -> model.features.target_sustainable_dividend
                                    (run with --run-labels after ~12 months of data)

Stages 2-4 only touch securities flagged ``dividend = TRUE`` in
``reference.securities``, so SEC and OpenBB are never called for non-payers.
Stages 5-6 need no network at all and run over whatever is already stored.
Stage 7 (labels) is refused on ``--limit``/``--tickers`` runs because labels
are immutable once written; a partial run would freeze wrong labels.

Usage:
    python -m scripts.run_full_etl
    python -m scripts.run_full_etl --limit 50
    python -m scripts.run_full_etl --tickers ACR-PC,ACR-PD
    python -m scripts.run_full_etl --skip-companyfacts --skip-sec-documents
    python -m scripts.run_full_etl --skip-derived
    python -m scripts.run_full_etl --run-labels --label-cutoff 2026-12-31
"""

import argparse
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

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
    parser.add_argument("--skip-dividend-data", action="store_true", help="Skip stage 2")
    parser.add_argument("--skip-companyfacts", action="store_true", help="Skip stage 3")
    parser.add_argument("--skip-sec-documents", action="store_true", help="Skip stage 4")
    parser.add_argument(
        "--skip-derived",
        action="store_true",
        help="Do not run offline derived stages 5 (fundamentals) and 6 (audit)",
    )
    parser.add_argument(
        "--skip-profiles", action="store_true", help="Do not refresh raw.ticker_profile in stage 2"
    )
    parser.add_argument(
        "--run-labels",
        action="store_true",
        help="Stage 7: populate target_sustainable_dividend from future dividend "
        "events (default off; refused on partial runs)",
    )
    parser.add_argument(
        "--label-cutoff",
        type=date.fromisoformat,
        default=None,
        help="Label horizon cutoff for stage 7 (default: today)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include non-dividend securities in stages 2-4 (not recommended)",
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
    dividend_args = list(base)
    if args.limit is not None:
        dividend_args += ["--limit", str(args.limit)]
    companyfacts_args = list(base)
    if args.limit is not None:
        companyfacts_args += ["--limit", str(args.limit)]
    sec_documents_args = list(base)

    ok = run_module("scripts.populate_raw_tables", raw_args, skip=args.skip_raw)
    if not ok:
        return 1

    ok = run_module("scripts.populate_reference_tables", reference_args, skip=args.skip_reference)
    if not ok:
        return 1

    if args.sources != "all":
        dividend_args += ["--sources", args.sources]
    if args.skip_profiles:
        dividend_args += ["--skip-profiles"]
    if args.all:
        dividend_args += ["--include-non-dividend"]
    ok = run_module("scripts.populate_dividend_data", dividend_args, skip=args.skip_dividend_data)
    if not ok:
        return 1

    if args.all:
        companyfacts_args += ["--all"]
    ok = run_module("scripts.populate_companyfacts", companyfacts_args, skip=args.skip_companyfacts)
    if not ok:
        return 1

    if args.all:
        sec_documents_args += ["--all"]
    ok = run_module(
        "scripts.populate_sec_documents", sec_documents_args, skip=args.skip_sec_documents
    )
    if not ok:
        return 1

    ok = run_module("scripts.populate_fundamentals", [], skip=args.skip_derived)
    if not ok:
        return 1

    ok = run_module("scripts.populate_audit", [], skip=args.skip_derived)
    if not ok:
        return 1

    if args.run_labels:
        label_args = ["--cutoff", args.label_cutoff.isoformat()] if args.label_cutoff else []
        ok = run_module("scripts.label_targets", label_args)
        if not ok:
            return 1

    print("\nFull ETL pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
