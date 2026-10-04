"""Periodic financials extraction from stored SEC XBRL companyfacts payloads.

DB-only: reads the normalized us-gaap facts already stored in
``raw.companyfacts`` and builds the relation layer
``fundamentals.periodic_financials``. No SEC, Yahoo, or OpenBB calls are
made, so the extractor is runnable offline and is idempotent (upsert keyed by
``(security_id, period_end, fiscal_period)``).
"""

from __future__ import annotations

from datetime import date

from .xbrl_tags import PERIODIC_FINANCIAL_CONCEPT_TAGS


def _concept_facts(facts):
    """Yield (concept_name, unit, record) tuples from an us-gaap concept map."""
    if not isinstance(facts, dict):
        return
    for concept_name, concept in facts.items():
        if not isinstance(concept, dict):
            continue
        units = concept.get("units")
        if not isinstance(units, dict):
            continue
        for unit, records in units.items():
            if not isinstance(records, list):
                continue
            for record in records:
                if isinstance(record, dict):
                    yield concept_name, unit, record


def _period_start(record):
    value = record.get("start")
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _period_end(record):
    value = record.get("end")
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


#: Most recent periods kept per metric. This must comfortably exceed the
#: longest lookback any feature can reference, because ``max_periods`` keeps
#: the *most recent* N periods and silently drops everything older. At the
#: previous value of 24 a continuously-reporting filer kept only roughly
#: 2020-2026, so the 2019-2022 fundamentals the 365-day label embargo needs
#: were discarded at extraction time and never reached the feature table. The
#: payloads are stored locally, so the cost of a larger bound is rows, not
#: network calls.
DEFAULT_MAX_PERIODS = 120


def _filed_date(record):
    """The date a fact became public, or None if the payload does not say.

    A fact with no filing date has no knowable availability, so it is dropped
    rather than guessed at. Assuming a conventional lag would silently invent
    availability the filing does not support; a SEC companyfacts fact always
    carries ``filed``, so in practice this rejects malformed records only.
    """
    value = record.get("filed")
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _visible_as_of(by_concept, as_of):
    """The value of one metric that was public on ``as_of``.

    ``by_concept`` maps concept priority -> {filing date: value}. Priority is
    consulted first, so the canonical tag order still decides *which* concept
    speaks; within that concept the most recent filing at or before ``as_of``
    wins. A period that was restated later therefore reports the original figure
    before the restatement and the restated figure after it.

    Resolving priority per concept matters: flattening the concepts into one
    date-keyed map would let a lower-priority concept that happened to file
    earlier overwrite the canonical one.
    """
    for _priority in sorted(by_concept):
        filings = by_concept[_priority]
        eligible = [filed for filed in filings if filed <= as_of]
        if eligible:
            return filings[max(eligible)]
    return None


def extract_periodic_financials(companyfacts, max_periods=DEFAULT_MAX_PERIODS):
    """Extract normalised periodic financial statements from a companyfacts payload.

    The SEC companyfacts graph reports the same economic fact under several
    near-equivalent us-gaap concepts; the canonical tag order in
    ``PERIODIC_FINANCIAL_CONCEPT_TAGS`` is followed, first reported concept
    wins. Flow facts (revenue, operating income, net income, EPS, cash-flow
    line items, capex) are carried over a fiscal period (``start``/``end``,
    YTD within the fiscal year) while instant facts (cash, assets, liabilities,
    debt, equity) are point-in-time balance-sheet amounts at ``end``.

    Rows are emitted as **vintages**: one row per ``(period, filing state)``,
    carrying the ``filed`` date at which that row's content became public. This
    exists because a period is not a single fact. The same ``period_end`` is
    reported once in the original filing and again in every later filing that
    repeats it as a comparative, and a company may restate it. Measured over a
    300-payload sample, 1,617 periods carry more than one distinct filing date,
    and the median lag from ``period_end`` to first filing is 224 days.

    Collapsing a period to its most recently filed value -- which is what this
    extractor used to do, and what the ``filed`` sort key was for -- makes the
    table impossible to query point-in-time. A consumer joining on
    ``period_end <= as_of_date`` sees the restated figure years before it was
    filed; a consumer joining on ``filed <= as_of_date`` against only the latest
    vintage sees nothing at all until the restatement, which is the opposite
    error and discards the original observation. Keeping every vintage lets the
    consumer resolve ``as_of`` correctly: pick the latest vintage whose
    ``filed`` is at or before the date being evaluated.

    Returns a list of dicts keyed by ``(period_end, fiscal_year,
    fiscal_period, filed)``.
    """
    payload = companyfacts.get("full_facts", companyfacts)
    us_gaap = {}
    for key, value in (payload.get("facts") or payload).items():
        if key == "us-gaap" and isinstance(value, dict):
            us_gaap = value
            break
    if not us_gaap:
        us_gaap = payload.get("us-gaap") or {}
    if not isinstance(us_gaap, dict):
        return []

    concepts = {}
    for concept_name, _unit, record in _concept_facts(us_gaap):
        concept = concepts.setdefault(concept_name, [])
        concept.append(record)

    # metric -> period key -> concept priority -> {filed: value}
    metric_periods: dict = {metric: {} for metric in PERIODIC_FINANCIAL_CONCEPT_TAGS}
    for metric, concept_names in PERIODIC_FINANCIAL_CONCEPT_TAGS.items():
        for priority, concept_name in enumerate(concept_names):
            for record in concepts.get(concept_name) or ():
                try:
                    value = float(record.get("val"))
                except (TypeError, ValueError):
                    continue
                period_end = _period_end(record)
                filed = _filed_date(record)
                if period_end is None or filed is None:
                    continue
                key = (period_end, record.get("fy"), record.get("fp") or "")
                by_concept = metric_periods[metric].setdefault(key, {})
                # Two facts from one filing for one period are the same
                # observation; a later filing for that concept supersedes it.
                by_concept.setdefault(priority, {})[filed] = value

    # period key -> metric -> concept priority -> {filed: value}, after the
    # per-metric recency bound. Grouping by period first matters: a vintage
    # belongs to the period, not to whichever metric happened to be restated.
    periods: dict = {}
    for metric, metric_periods in metric_periods.items():
        latest = sorted(metric_periods.items(), key=lambda item: item[0][0], reverse=True)
        for key, by_concept in latest[:max_periods]:
            periods.setdefault(key, {})[metric] = by_concept

    rows: dict[tuple, dict] = {}
    for (period_end, fiscal_year, fiscal_period), per_metric in periods.items():
        # Every date on which *anything* in this period changed hands is a
        # vintage. Resolving each metric at each of those dates is what makes a
        # snapshot consistent: a metric that was not restated carries its last
        # filed value forward instead of vanishing from the later snapshot.
        vintages = sorted(
            {
                filed
                for by_concept in per_metric.values()
                for filings in by_concept.values()
                for filed in filings
            }
        )
        for vintage in vintages:
            row = rows.setdefault(
                (period_end, fiscal_year, fiscal_period, vintage),
                {
                    "period_end": period_end,
                    "fiscal_year": fiscal_year,
                    "fiscal_period": fiscal_period or "FY",
                    "filed": vintage,
                },
            )
            for metric, by_concept in per_metric.items():
                value = _visible_as_of(by_concept, vintage)
                # Absent until the metric is public, then carried forward.
                if value is not None:
                    row[metric] = value

    result = []
    for row in rows.values():
        row = dict(row)
        ocf = row.get("operating_cash_flow")
        capex = row.get("capital_expenditures")
        if ocf is not None and capex is not None:
            row["free_cash_flow"] = ocf - capex
        # Total debt is the sum of whichever components the filer reported.
        # Summing rather than priority-resolving is deliberate: see the comment
        # on the component tags. A component that was never reported is not
        # treated as zero -- if nothing at all was reported, debt stays absent,
        # which is what lets C2/C3 tell "no debt instruments" from "debt
        # withheld".
        parts = [
            row.get(part)
            for part in (
                "debt_noncurrent",
                "debt_current",
                "finance_lease_debt",
            )
        ]
        reported = [part for part in parts if part is not None]
        if reported:
            row["debt"] = sum(reported)
        row["source"] = "SEC_XBRL"
        result.append(row)
    return result
