"""
Populate the offline ML target ``model.features.target_sustainable_dividend``.

Labels are derived from future dividend events in ``raw.dividend_data`` — never
fabricated. See ``docs/model-labeling-plan.md`` for the full plan.

Per feature row at ``as_of_date`` (365-day outcome window):

- **1** — at least one positive dividend event with ex-date inside the window.
- **0** — no in-window positive payment, but monitoring extends to or past the
  window end (any later/at-window-end dividend record, even ``amount = 0``,
  proves the security was still tracked — a genuine cut/omission, not a loss
  of coverage).
- **NULL** — window end is not yet covered by monitoring data: not enough
  evidence, left unlabeled.

Only rows whose outcome window fully elapses before ``--cutoff`` are labeled.
Previously labeled rows are left untouched unless ``--rebuild`` is passed, so
labels consumed in training are never silently rewritten.

After labeling, record the walk-forward checkpoint (Azure Go/No-Go):

    python -m scripts.label_targets
    python -m scripts.evaluate_walk_forward

Usage:
    python -m scripts.label_targets
    python -m scripts.label_targets --cutoff 2026-12-31
    python -m scripts.label_targets --rebuild
"""

import argparse
import sys
from datetime import date, timedelta

from sqlalchemy import text

from src.crispdm.db import engine

OUTCOME_WINDOW_DAYS = 365


def label_value(has_in_window, last_ex_date, as_of_date):
    """Return the label (int 1/0) or None for one feature row.

    ``as_of_date`` eligibility (window elapsed before cutoff) is enforced by the
    caller/query; this only decides 1 vs 0 vs insufficient evidence.
    """
    if has_in_window:
        return 1
    window_end = as_of_date + timedelta(days=OUTCOME_WINDOW_DAYS)
    if last_ex_date is not None and last_ex_date >= window_end:
        return 0
    return None


def label_targets(cutoff, rebuild=False):
    """Label eligible feature rows; return (total, positive, negative)."""
    eligible_before = cutoff - timedelta(days=OUTCOME_WINDOW_DAYS)
    overwrite = "AND f.target_sustainable_dividend IS NULL" if not rebuild else ""

    with engine.begin() as c:
        rows = c.execute(
            text(
                f"""
                WITH monitor AS (
                  SELECT security_id, MAX(ex_dividend_date) AS last_ex
                  FROM raw.dividend_data
                  GROUP BY security_id
                )
                UPDATE model.features f
                SET target_sustainable_dividend = CASE
                  WHEN EXISTS (
                    SELECT 1 FROM raw.dividend_data d
                    WHERE d.security_id = f.security_id
                      AND d.ex_dividend_date > f.as_of_date
                      AND d.ex_dividend_date <= f.as_of_date
                                           + INTERVAL '{OUTCOME_WINDOW_DAYS} days'
                      AND d.amount > 0
                  ) THEN 1
                  WHEN m.last_ex >= f.as_of_date
                                  + INTERVAL '{OUTCOME_WINDOW_DAYS} days' THEN 0
                  ELSE NULL
                END
                FROM monitor m
                WHERE m.security_id = f.security_id
                  AND f.as_of_date <= :eligible_before
                  {overwrite}
                RETURNING f.security_id, f.as_of_date, f.target_sustainable_dividend
                """
            ),
            {"eligible_before": eligible_before},
        ).fetchall()

    total = len(rows)
    positive = sum(1 for _, _, label in rows if label == 1)
    negative = sum(1 for _, _, label in rows if label == 0)
    return total, positive, negative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cutoff",
        type=date.fromisoformat,
        default=date.today(),
        help="Label horizon cutoff (default: today). Rows must have a fully "
        "elapsed 365-day outcome window before this date.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Overwrite existing labels instead of leaving them immutable.",
    )
    args = parser.parse_args()

    total, positive, negative = label_targets(args.cutoff, rebuild=args.rebuild)
    print(
        f"[label] cutoff={args.cutoff} eligible_window_start="
        f"{args.cutoff - timedelta(days=OUTCOME_WINDOW_DAYS)} "
        f"labeled={total} positive={positive} negative={negative}"
    )
    if total == 0:
        print(
            "[label] no eligible rows (need feature rows with a full 365-day "
            "outcome window elapsed before the cutoff). Nothing written."
        )
        return 0

    uncertain = total - positive - negative
    if uncertain:
        print(
            f"[label] {uncertain} otherwise-eligible rows left NULL (monitoring "
            "data does not extend past the window end)."
        )
    print(
        "[label] next: python -m scripts.evaluate_walk_forward\n"
        "        (records the walk-forward checkpoint in audit.model_runs)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
