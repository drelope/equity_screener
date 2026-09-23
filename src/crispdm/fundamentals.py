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


def extract_periodic_financials(companyfacts, max_periods=24):
    """Extract normalised periodic financial statements from a companyfacts payload.

    The SEC companyfacts graph reports the same economic fact under several
    near-equivalent us-gaap concepts; the canonical tag order in
    ``PERIODIC_FINANCIAL_CONCEPT_TAGS`` is followed, first reported concept
    wins. Flow facts (revenue, operating income, net income, EPS, cash-flow
    line items, capex) are carried over a fiscal period (``start``/``end``,
    YTD within the fiscal year) while instant facts (cash, assets, liabilities,
    debt, equity) are point-in-time balance-sheet amounts at ``end``. The most
    recently filed value for each (metric, period) is kept, and the most recent
    ``max_periods`` periods per metric are returned.

    Returns a list of dicts, one per ``(period_end, fiscal_year,
    fiscal_period)`` combination present in the payload.
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

    # metric -> {(period_end, fy, fp): (priority_index, filed_sort, value)}
    metric_periods = {metric: {} for metric in PERIODIC_FINANCIAL_CONCEPT_TAGS}
    for metric, concept_names in PERIODIC_FINANCIAL_CONCEPT_TAGS.items():
        for priority, concept_name in enumerate(concept_names):
            for record in concepts.get(concept_name) or ():
                try:
                    value = float(record.get("val"))
                except (TypeError, ValueError):
                    continue
                period_end = _period_end(record)
                if period_end is None:
                    continue
                fiscal_year = record.get("fy")
                fiscal_period = record.get("fp") or ""
                key = (period_end, fiscal_year, fiscal_period)
                filed = str(record.get("filed") or record.get("accn") or "")
                existing = metric_periods[metric]
                if key not in existing or (
                    priority < existing[key][0]
                    or (priority == existing[key][0] and filed > existing[key][1])
                ):
                    existing[key] = (priority, filed, value)

    rows: dict[tuple[date, int, str], dict] = {}
    for metric, periods in metric_periods.items():
        latest = sorted(periods.items(), key=lambda item: item[0][0], reverse=True)
        for key, (_priority, _filed, value) in latest[:max_periods]:
            period_end, fiscal_year, fiscal_period = key
            row = rows.setdefault(key, {})
            row["period_end"] = period_end
            row["fiscal_year"] = fiscal_year
            row["fiscal_period"] = fiscal_period or "FY"
            row[metric] = value

    result = []
    for row in rows.values():
        row = dict(row)
        ocf = row.get("operating_cash_flow")
        capex = row.get("capital_expenditures")
        if ocf is not None and capex is not None:
            row["free_cash_flow"] = ocf - capex
        row["source"] = "SEC_XBRL"
        result.append(row)
    return result
