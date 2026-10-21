"""Sections, fields and export format for the investment-analysis worksheet.

This module is the single source of truth for the worksheet rendered by
``app.views.investment_analysis``: the workflow order, each section's fields, their
types and options, validation on save, and the Markdown/JSON export. The canonical
workflow document (``docs/InvestmentAnalysisWorkflow.md``) is written to match it —
when the two disagree, this code wins and the document is corrected.

Payload shape (stored verbatim in ``analysis.investment_analyses.payload``)::

    {"version": 1, "sections": {"<section_id>": {"<field_id>": value, ...}, ...}}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

SCHEMA_VERSION = 1

#: Unset value of every select widget; validation rejects it on required fields and
#: it is stored as an empty string in the payload.
PLACEHOLDER = "(not set)"

CONFIDENCE_OPTIONS = ("High", "Medium", "Low")
RISK_OPTIONS = ("High", "Moderate", "Low")
YES_NO = ("Present", "Absent")
MARGIN_OPTIONS = ("Expanding", "Flat", "Compressing")

KINDS = ("text", "textarea", "select", "score")

_SENTENCE_TERMINATOR = re.compile(r"[.!?](?=\s|$)")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_ABBREVIATIONS = frozenset(
    {
        "approx",
        "co",
        "corp",
        "dept",
        "dr",
        "e.g",
        "est",
        "etc",
        "fig",
        "i.e",
        "inc",
        "jr",
        "ltd",
        "mr",
        "mrs",
        "ms",
        "no",
        "sr",
        "st",
        "u.k",
        "u.s",
        "u.s.a",
        "vs",
    }
)
_PLACEHOLDER_VALUES = frozenset(
    {
        PLACEHOLDER.lower(),
        "n/a",
        "n/a.",
        "n.a",
        "n.a.",
        "na",
        "none",
        "none.",
        "null",
        "nil",
        "-",
        "--",
        "—",
        "–",
        "tbd",
        "todo",
        "unknown",
        "unavailable",
        "not applicable",
        "not available",
        "not loaded",
        "not reported",
        "not set",
        "pending",
    }
)


@dataclass(frozen=True)
class Field:
    """One worksheet input. ``kind`` selects the widget and the stored type."""

    id: str
    label: str
    kind: str = "text"
    options: tuple[str, ...] = ()
    required: bool = False
    help: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"{self.id}: unknown kind {self.kind!r}")
        if self.kind == "select" and not self.options:
            raise ValueError(f"{self.id}: a select needs options")


@dataclass(frozen=True)
class Section:
    """One workflow step. ``has_confidence`` appends the section's confidence block."""

    id: str
    title: str
    fields: tuple[Field, ...] = field(default_factory=tuple)
    has_confidence: bool = True
    intro: str = ""

    @property
    def all_fields(self) -> tuple[Field, ...]:
        extra: list[Field] = []
        if self.has_confidence:
            extra.append(
                Field("confidence", "Confidence level", "select", CONFIDENCE_OPTIONS, required=True)
            )
            extra.append(Field("confidence_note", "Confidence note (required when Low)", "textarea"))
        extra.append(Field("sources", "Sources & citations", "textarea"))
        return self.fields + tuple(extra)

    def field(self, field_id: str) -> Field | None:
        return next((f for f in self.all_fields if f.id == field_id), None)


def _f(field_id: str, label: str, kind: str = "text", **kwargs) -> Field:
    return Field(field_id, label, kind, **kwargs)


CONFIDENCE_NOTE_REQUIRED = "a Low confidence level needs a confidence note"


def _is_blank(value) -> bool:
    """True for empty values and bare placeholders such as ``N/A`` or ``TBD``.

    Only the whole value is matched, so explanatory text that mentions ``N/A`` (for
    example an optional field documenting missing data) is not treated as blank.
    """
    text = " ".join(("" if value is None else str(value)).strip().split()).lower()
    return not text or text in _PLACEHOLDER_VALUES


SECTIONS: tuple[Section, ...] = (
    Section(
        "universe",
        "Investment universe",
        (
            _f(
                "universe_filters",
                "Filters applied",
                required=True,
                help="Sector, market-cap and geographic filters",
            ),
            _f("universe_rationale", "Why this universe", "textarea"),
        ),
        has_confidence=False,
        intro="Define the hunting ground before looking at anything.",
    ),
    Section(
        "macro",
        "Macro & credit",
        (
            _f(
                "macro_backdrop",
                "Backdrop",
                "textarea",
                required=True,
                help="Growth, inflation, rates and the prevailing regime",
            ),
            _f("ig_spreads", "Investment grade spreads vs. historical average"),
            _f("hy_spreads", "High yield spreads vs. historical average"),
            _f(
                "cds_trend",
                "CDS spread trend",
                "select",
                options=("Improving", "Flat", "Deteriorating"),
            ),
            _f("default_rates", "Default rates (current vs. trend)"),
            _f("distressed_ratio", "Distressed debt ratio"),
            _f("refinancing_wall", "Refinancing wall (near-term maturities)"),
            _f("index_put_call_ratio", "Index put/call ratio (options positioning)"),
            _f("vix_term_structure", "VIX term structure (front vs. 3M)"),
            _f(
                "credit_verdict",
                "Credit market verdict",
                "select",
                options=("Bullish", "Neutral", "Bearish"),
                required=True,
            ),
            _f("credit_rationale", "Credit verdict rationale", "textarea", required=True),
        ),
        intro="Critical for banks, REITs, preferred securities, leveraged companies and cyclicals.",
    ),
    Section(
        "industry",
        "Industry analysis",
        (
            _f("industry_outlook", "Outlook", "textarea", required=True),
            _f("competitive_landscape", "Competitive landscape", "textarea"),
        ),
    ),
    Section(
        "capital_cycle",
        "Industry structure & capital cycle",
        (
            _f("capacity_growth", "Capacity growth (X% YoY, trend)"),
            _f(
                "competitor_capex",
                "Competitor capex trend",
                "select",
                options=("Increasing", "Decreasing", "Stable"),
            ),
            _f("supply_changes", "Supply additions / removals"),
            _f("barriers", "Barriers to entry", "select", options=RISK_OPTIONS, required=True),
            _f("utilization", "Utilization (current vs. historical average)"),
            _f(
                "profitability_trend",
                "Industry profitability trend",
                "select",
                options=("Improving", "Deteriorating", "Stable"),
            ),
            _f(
                "capital_discipline_score",
                "Capital discipline score (1-10)",
                "score",
                required=True,
                help="1-3 poor (overbuilding, destructive competition); 4-6 moderate; "
                "7-10 strong (rational, returns-focused)",
            ),
        ),
        intro="Essential for semiconductors, energy, mining, shipping, chemicals, REITs "
        "and industrials: supply constraints drive many opportunities more than "
        "revenue growth.",
    ),
    Section(
        "supply",
        "Supply side",
        (_f("supply_analysis", "Supply-side analysis", "textarea", required=True),),
    ),
    Section(
        "demand",
        "Demand side",
        (_f("demand_analysis", "Demand-side analysis", "textarea", required=True),),
    ),
    Section(
        "consensus",
        "Consensus expectations",
        (
            _f("fy_revenue_est", "Current FY revenue estimate"),
            _f("fy_eps_est", "Current FY EPS estimate"),
            _f("next_fy_revenue_est", "Next FY revenue estimate"),
            _f("next_fy_eps_est", "Next FY EPS estimate"),
            _f(
                "revision_trend",
                "Estimate revision trend",
                "select",
                options=("Upward", "Flat", "Downward"),
            ),
            _f(
                "estimate_dispersion",
                "Estimate dispersion",
                "select",
                options=("Low", "Moderate", "High"),
            ),
            _f("surprise_implication", "Implication for earnings surprise", "textarea"),
            _f("options_implied_move", "Options-implied move (front expiry)"),
        ),
        has_confidence=False,
        intro="Makes expectation mismatches identifiable before thesis formation.",
    ),
    Section(
        "variant",
        "Variant perception (highest priority)",
        (
            _f("consensus_revenue_growth", "Consensus: revenue growth"),
            _f("consensus_eps_growth", "Consensus: EPS growth"),
            _f("consensus_margins", "Consensus: margins", "select", options=MARGIN_OPTIONS),
            _f("consensus_capital_allocation", "Consensus: capital allocation"),
            _f("consensus_multiple", "Consensus: valuation multiple"),
            _f("my_revenue_growth", "My view: revenue growth"),
            _f("my_eps_growth", "My view: EPS growth"),
            _f("my_margins", "My view: margins", "select", options=MARGIN_OPTIONS),
            _f("my_capital_allocation", "My view: capital allocation"),
            _f("my_multiple", "My view: valuation multiple"),
            _f(
                "options_positioning",
                "Options positioning and crowding (supporting)",
                "textarea",
            ),
            _f(
                "bullish_variant",
                "Why the market may be wrong (bullish)",
                "textarea",
                required=True,
            ),
            _f(
                "bearish_variant",
                "Why the market may be wrong (bearish)",
                "textarea",
                required=True,
            ),
            _f(
                "key_evidence",
                "Key evidence (one per line, minimum three)",
                "textarea",
                required=True,
            ),
        ),
        intro="Forces identification of informational, analytical and behavioural edge — "
        "the source of excess returns.",
    ),
    Section(
        "company",
        "Company deep-dive",
        (
            _f("business_model", "Business model", "textarea", required=True),
            _f("financial_analysis", "Financial analysis", "textarea", required=True),
        ),
        intro="Read the warehouse context panel first: features, scores and fundamentals.",
    ),
    Section(
        "earnings_quality",
        "Earnings quality",
        (
            _f("cash_conversion", "Cash conversion (CFO / net income, vs. historical)"),
            _f("accrual_ratio", "Accrual ratio ((NI - CFO) / total assets)"),
            _f("sbc_pct", "SBC as % of revenue"),
            _f("gaap_gap", "GAAP vs. non-GAAP gap"),
            _f("working_capital", "Working capital impact (source / use of cash)"),
            _f("one_time_items", "Recurring vs. one-time adjustments", "textarea"),
            _f(
                "quality_verdict",
                "Verdict",
                "select",
                options=("High quality", "Moderate", "Low quality"),
                required=True,
            ),
            _f("red_flags", "Red flags", "textarea"),
        ),
        intro="Identifies low-quality earnings before they distort valuation.",
    ),
    Section(
        "moat",
        "Competitive advantage",
        (
            _f("network_effects", "Network effects", "select", options=YES_NO),
            _f("scale_advantage", "Scale advantage", "select", options=YES_NO),
            _f("brand_strength", "Brand strength", "select", options=YES_NO),
            _f("switching_costs", "Switching costs", "select", options=RISK_OPTIONS),
            _f("cost_leadership", "Cost leadership", "select", options=YES_NO),
            _f("regulatory_advantage", "Regulatory advantage", "select", options=YES_NO),
            _f(
                "moat_rating",
                "Moat rating",
                "select",
                options=("Strong", "Moderate", "Weak", "None"),
                required=True,
            ),
            _f(
                "durability_trend",
                "Durability trend",
                "select",
                options=("Improving", "Stable", "Eroding"),
            ),
        ),
        intro="Separates compounders from cyclical trades and value traps.",
    ),
    Section(
        "management",
        "Management assessment",
        (
            _f("track_record", "Track record (delivery vs. promises)", "textarea"),
            _f("capital_allocation_history", "Capital allocation history", "textarea"),
            _f("guidance_accuracy", "Guidance accuracy (beat/miss pattern)"),
            _f("insider_ownership", "Insider ownership (%)"),
            _f(
                "insider_transactions",
                "Insider transactions (12M)",
                "select",
                options=("Buying", "Selling", "Mixed", "None"),
            ),
            _f("compensation_alignment", "Compensation alignment", "textarea"),
            _f("management_score", "Management score (1-10)", "score", required=True),
        ),
        intro="Execution risk and stewardship quality.",
    ),
    Section(
        "valuation",
        "Valuation",
        (
            _f("valuation_methods", "Methods and arithmetic", "textarea", required=True),
            _f(
                "key_assumptions",
                "Key assumptions",
                "textarea",
                required=True,
                help="Every forward-looking statement needs an explicit assumption",
            ),
            _f("target_price", "Target price (with currency)"),
            _f("margin_of_safety", "Margin of safety vs. current price"),
        ),
    ),
    Section(
        "scenarios",
        "Scenarios",
        (
            _f("base_case", "Base case", "textarea", required=True),
            _f("bull_case", "Bull case", "textarea", required=True),
            _f("bear_case", "Bear case", "textarea", required=True),
            _f("scenario_probabilities", "Probabilities (base / bull / bear)"),
            _f("expected_return", "Probability-weighted forward 12M return"),
        ),
    ),
    Section(
        "analog",
        "Historical analogs",
        (
            _f(
                "similar_setups",
                "Similar historical setups (markdown table, 3+ rows)",
                "textarea",
                required=True,
                help="Columns: date | conditions | forward 12M total return | outcome",
            ),
            _f("base_rate", "Base rate (% positive returns)"),
            _f("key_differences", "Key differences today", "textarea"),
            _f("analog_implication", "Implication for the current setup", "textarea"),
        ),
        intro="Prevents narrative-driven conclusions; improves probabilistic thinking.",
    ),
    Section(
        "risk",
        "Risk decomposition",
        (
            _f("business_risk", "Business risk", "select", options=RISK_OPTIONS, required=True),
            _f("valuation_risk", "Valuation risk", "select", options=RISK_OPTIONS, required=True),
            _f(
                "balance_sheet_risk",
                "Balance-sheet risk",
                "select",
                options=RISK_OPTIONS,
                required=True,
            ),
            _f("macro_risk", "Macro risk", "select", options=RISK_OPTIONS, required=True),
            _f("regulatory_risk", "Regulatory risk", "select", options=RISK_OPTIONS, required=True),
            _f("liquidity_risk", "Liquidity risk", "select", options=RISK_OPTIONS, required=True),
            _f("options_iv", "Options: ATM implied volatility (vs. realized)"),
            _f("options_skew", "Options: 25-delta skew"),
            _f("options_term_structure", "Options: term-structure slope"),
            _f("options_liquidity", "Options: open interest and bid-ask liquidity"),
            _f(
                "options_data_status",
                "Options data status",
                "select",
                options=("Observed", "Derived", "Unavailable"),
            ),
            _f("overall_risk_score", "Overall risk score (1-10)", "score", required=True),
            _f("position_sizing", "Position sizing implication", "textarea", required=True),
        ),
        intro="Enables differentiated position sizing by risk category rather than a "
        "generic 'risk is moderate'.",
    ),
    Section(
        "portfolio",
        "Portfolio integration",
        (
            _f("factor_growth", "Growth", "select", options=RISK_OPTIONS),
            _f("factor_value", "Value", "select", options=RISK_OPTIONS),
            _f("factor_quality", "Quality", "select", options=RISK_OPTIONS),
            _f(
                "factor_momentum", "Momentum", "select", options=("Positive", "Neutral", "Negative")
            ),
            _f("factor_low_volatility", "Low volatility", "select", options=RISK_OPTIONS),
            _f("factor_size", "Size", "select", options=("Large", "Mid", "Small")),
            _f("factor_rate_duration", "Interest rate duration", "select", options=RISK_OPTIONS),
            _f("factor_usd_exposure", "USD exposure", "select", options=RISK_OPTIONS),
            _f("existing_tilts", "Existing portfolio tilts", "textarea"),
            _f("position_adds", "What this position adds", "textarea"),
            _f("concentration_risk", "Concentration risk", "textarea"),
            _f("correlation_assessment", "Correlation assessment", "textarea"),
        ),
        has_confidence=False,
        intro="Avoids unintended factor concentration at the portfolio level.",
    ),
    Section(
        "final",
        "Recommendation & final output",
        (
            _f("thesis", "Thesis (3 sentences maximum)", required=True),
            _f(
                "recommendation",
                "Recommendation",
                "select",
                options=("Buy", "Add", "Hold", "Trim", "Sell"),
                required=True,
            ),
            _f("variant_summary", "Variant perception summary", "textarea", required=True),
            _f("risk_summary", "Risk decomposition summary", "textarea", required=True),
            _f("position_recommendation", "Position sizing recommendation", required=True),
            _f(
                "catalyst_timeline",
                "Catalyst timeline (what changes the view)",
                "textarea",
                required=True,
            ),
            _f(
                "kill_switch",
                "Kill switch (what invalidates the thesis)",
                "textarea",
                required=True,
            ),
            _f(
                "confidence_overall",
                "Overall confidence level",
                "select",
                options=CONFIDENCE_OPTIONS,
                required=True,
            ),
            _f("data_quality", "Confidence reason: data quality", "textarea", required=True),
            _f(
                "forecast_uncertainty",
                "Confidence reason: forecast uncertainty",
                "textarea",
                required=True,
            ),
            _f(
                "sensitivity_assumptions",
                "Confidence reason: sensitivity to assumptions",
                "textarea",
                required=True,
            ),
            _f(
                "variant_conviction",
                "Confidence reason: variant perception conviction",
                "textarea",
                required=True,
            ),
        ),
        has_confidence=False,
        intro="No recommendation without a risk decomposition; no conclusion before "
        "steps 1-17 are complete.",
    ),
)

SECTION_BY_ID = {section.id: section for section in SECTIONS}


def empty_payload() -> dict:
    """A blank payload with every select unset and every text field empty."""
    sections: dict[str, dict] = {}
    for section in SECTIONS:
        values: dict[str, str | int | None] = {}
        for f in section.all_fields:
            if f.kind == "select":
                values[f.id] = ""
            elif f.kind == "score":
                values[f.id] = None
            else:
                values[f.id] = ""
        sections[section.id] = values
    return {"version": SCHEMA_VERSION, "sections": sections}


def get_value(payload: dict, section_id: str, field_id: str):
    return payload.get("sections", {}).get(section_id, {}).get(field_id)


def completion(payload: dict) -> tuple[int, int]:
    """Filled required fields vs. total required fields, across the whole worksheet.

    The conditional confidence note is left to :func:`validate`/:func:`validate_draft`:
    it is only required when a section records Low confidence, so counting it here would
    keep the progress bar incomplete on an otherwise finished worksheet.
    """
    filled = total = 0
    for section in SECTIONS:
        values = _values(payload, section)
        for f in section.all_fields:
            if f.required:
                total += 1
                if _present_in(values, f):
                    filled += 1
    return filled, total


def section_completion(payload: dict) -> dict[str, tuple[int, int]]:
    """Filled vs. total required fields for each section, keyed by section id."""
    out: dict[str, tuple[int, int]] = {}
    for section in SECTIONS:
        required = [f for f in section.all_fields if f.required]
        values = _values(payload, section)
        filled = sum(1 for f in required if _present_in(values, f))
        out[section.id] = (filled, len(required))
    return out


def _values(payload: dict, section: Section) -> dict:
    values = payload.get("sections", {}).get(section.id, {})
    return values if isinstance(values, dict) else {}


def _present_in(values: dict, f: Field) -> bool:
    value = values.get(f.id)
    if f.kind == "score":
        return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10
    if f.kind == "select":
        return value is not None and str(value).strip() in f.options
    return not _is_blank(value)


def missing_required_fields(payload: dict) -> dict[str, list[str]]:
    """Missing required field labels per section id; sections with none are omitted.

    ``app.views.investment_analysis`` uses this to label incomplete steps, so an
    analyst sees which fields a section still needs rather than only a count.
    """
    out: dict[str, list[str]] = {}
    for section in SECTIONS:
        values = _values(payload, section)
        missing = [f.label for f in section.all_fields if f.required and not _present_in(values, f)]
        if missing:
            out[section.id] = missing
    return out


def missing_prior_step_fields(payload: dict) -> list[str]:
    """``Section / Field`` lines for every missing required field outside the final step.

    The recommendation gate depends on exactly these fields, so the page lists them
    instead of only saying steps 1-17 are incomplete.
    """
    lines: list[str] = []
    for section in SECTIONS:
        if section.id == "final":
            continue
        values = _values(payload, section)
        for f in section.all_fields:
            if f.required and not _present_in(values, f):
                lines.append(f"{section.title} / {f.label}")
    return lines


def _present(payload: dict, section: Section, f: Field) -> bool:
    return _present_in(_values(payload, section), f)


def _label(section: Section, f: Field) -> str:
    return f"{section.title} / {f.label}"


def validate(payload: dict) -> list[str]:
    """Every rule that must hold before the worksheet can be saved as Final. Empty = valid."""
    errors = _structural_errors(payload)
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        return errors
    errors.extend(_required_errors(sections))
    errors.extend(_conditional_errors(sections))
    return errors


def validate_draft(payload: dict) -> list[str]:
    """The lighter rule set for saving incomplete work as a draft.

    A draft only needs a well-formed payload, at least one filled field, and — because a
    recommendation is a conclusion — steps 1-17 complete *and* the final narrative present
    before the recommendation is set. The remaining analytical-quality rules are deferred
    to :func:`validate`.
    """
    errors = _structural_errors(payload)
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        return errors
    if not _has_any_value(payload):
        errors.append("the worksheet is empty; fill in at least one field before saving")
        return errors
    errors.extend(_recommendation_errors(sections))
    if _has_recommendation(sections):
        final = SECTION_BY_ID["final"]
        values = sections.get("final", {})
        for f in final.all_fields:
            if f.required and not _present_in(values, f):
                errors.append(f"{_label(final, f)}: required once a recommendation is recorded")
        errors.extend(_rule_thesis(sections))
    return errors


def _has_recommendation(sections: dict) -> bool:
    return bool(str(sections.get("final", {}).get("recommendation") or "").strip())


def prior_steps_complete(payload: dict) -> bool:
    """True when every required field outside the final section is filled."""
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        return False
    return not _incomplete_prior_steps(sections)


def _structural_errors(payload: dict) -> list[str]:
    """Payload-shape problems: independent of whether the worksheet is a draft or final."""
    errors: list[str] = []
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        return ["the payload has no sections"]
    for section in SECTIONS:
        values = sections.get(section.id)
        if not isinstance(values, dict):
            errors.append(f"{section.title}: section is missing")
            continue
        for f in section.all_fields:
            raw = values.get(f.id)
            where = _label(section, f)
            if f.kind == "select":
                text = "" if raw is None else str(raw).strip()
                if text == PLACEHOLDER:
                    text = ""
                if text and text not in f.options:
                    errors.append(f"{where}: {text!r} is not one of the options")
            elif f.kind == "score" and raw not in (None, ""):
                if not isinstance(raw, int) or not 1 <= raw <= 10:
                    errors.append(f"{where}: must be a whole number from 1 to 10")
    return errors


def _required_errors(sections: dict) -> list[str]:
    """Every required field present and non-empty."""
    errors: list[str] = []
    for section in SECTIONS:
        values = sections.get(section.id)
        if not isinstance(values, dict):
            continue
        for f in section.all_fields:
            if not f.required:
                continue
            raw = values.get(f.id)
            where = _label(section, f)
            if f.kind == "score":
                if not _present_in(values, f):
                    errors.append(f"{where}: required")
            elif f.kind == "select":
                if not _present_in(values, f):
                    errors.append(f"{where}: required")
            elif _is_blank(raw):
                errors.append(f"{where}: required")
    return errors


def _conditional_errors(sections: dict) -> list[str]:
    """Cross-field rules, only meaningful once the analyst has entered the data."""
    errors: list[str] = []
    for section in SECTIONS:
        if not section.has_confidence:
            continue
        values = sections.get(section.id)
        if not isinstance(values, dict):
            continue
        confidence = str(values.get("confidence", "")).strip()
        if confidence == "Low" and not str(values.get("confidence_note") or "").strip():
            errors.append(f"{section.title}: {CONFIDENCE_NOTE_REQUIRED}")
    errors.extend(_rule_evidence(sections))
    errors.extend(_rule_thesis(sections))
    errors.extend(_rule_probabilities(sections))
    errors.extend(_rule_base_rate(sections))
    return errors


def _recommendation_errors(sections: dict) -> list[str]:
    """The hard constraint: no recommendation before steps 1-17 are complete."""
    recommendation = str(sections.get("final", {}).get("recommendation") or "").strip()
    if not recommendation:
        return []
    incomplete = _incomplete_prior_steps(sections)
    if not incomplete:
        return []
    return [
        "Recommendation / Recommendation: cannot be set until steps 1-17 are complete "
        f"(still incomplete: {', '.join(incomplete)})"
    ]


def _incomplete_prior_steps(sections: dict) -> list[str]:
    missing: list[str] = []
    for section in SECTIONS:
        if section.id == "final":
            continue
        values = sections.get(section.id)
        if not isinstance(values, dict):
            missing.append(section.title)
            continue
        if any(f.required and not _present_in(values, f) for f in section.all_fields):
            missing.append(section.title)
    return missing


def _has_any_value(payload: dict) -> bool:
    for section in SECTIONS:
        values = _values(payload, section)
        if any(_present_in(values, f) for f in section.all_fields):
            return True
    return False


def _rule_evidence(sections: dict) -> list[str]:
    lines = _lines(sections, "variant", "key_evidence")
    if lines and len(lines) < 3:
        return ["Variant perception / Key evidence: needs at least three lines"]
    return []


def _sentence_count(text: str) -> int:
    """Count sentences without treating abbreviations like ``Inc.`` or ``U.S.`` as ends."""
    count = 0
    for match in _SENTENCE_TERMINATOR.finditer(text):
        if match.group() == ".":
            prefix = text[: match.end()]
            token_match = re.search(r"([A-Za-z][A-Za-z.]*)\.$", prefix)
            token = token_match.group(1).lower() if token_match else ""
            following = text[match.end() :].lstrip()
            # Initials (J. Smith) are never sentence ends; abbreviations before a
            # lower-case word, a digit or the end of the text are part of the sentence.
            if token and len(token) == 1:
                continue
            if token in _ABBREVIATIONS:
                if not following or following[0].islower() or following[0].isdigit():
                    continue
        count += 1
    return count


def _rule_thesis(sections: dict) -> list[str]:
    thesis = str(sections.get("final", {}).get("thesis") or "").strip()
    if thesis and _sentence_count(thesis) > 3:
        return ["Recommendation / Thesis: must be three sentences or fewer"]
    return []


def _rule_probabilities(sections: dict) -> list[str]:
    raw = str(sections.get("scenarios", {}).get("scenario_probabilities") or "").strip()
    if not _NUMBER.search(raw):
        return []
    numbers = [float(n) for n in _NUMBER.findall(raw)]
    where = "Scenarios / Probabilities (base / bull / bear)"
    if len(numbers) != 3:
        return [f"{where}: enter exactly three numbers (base / bull / bear)"]
    if abs(sum(numbers) - 100.0) > 0.01:
        return [f"{where}: the three numbers must sum to 100"]
    return []


def _rule_base_rate(sections: dict) -> list[str]:
    raw = str(sections.get("analog", {}).get("base_rate") or "").strip()
    if not _NUMBER.search(raw):
        return []
    numbers = [float(n) for n in _NUMBER.findall(raw)]
    where = "Historical analogs / Base rate (% positive returns)"
    if len(numbers) != 1 or not 0.0 <= numbers[0] <= 100.0:
        return [f"{where}: enter a single percentage between 0 and 100"]
    return []


def _lines(sections: dict, section_id: str, field_id: str) -> list[str]:
    raw = sections.get(section_id, {}).get(field_id) or ""
    return [line.strip() for line in str(raw).splitlines() if line.strip()]


def to_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def final_summary(payload: dict) -> dict:
    """The four denormalised columns of ``analysis.investment_analyses``.

    Read from the final section; a missing or partial section yields empty/None values
    so the caller can save an unfinished worksheet as a draft.
    """
    final = payload.get("sections", {}).get("final", {})
    risk = get_value(payload, "risk", "overall_risk_score")
    return {
        "thesis": str(final.get("thesis") or ""),
        "recommendation": str(final.get("recommendation") or "") or None,
        "confidence": str(final.get("confidence_overall") or "") or None,
        "overall_risk_score": int(risk) if isinstance(risk, int) else None,
    }


def to_markdown(
    payload: dict,
    ticker: str,
    *,
    status: str | None = None,
    saved_by: str | None = None,
    saved_at: str | None = None,
) -> str:
    """The canonical document form: workflow order, one ``##`` heading per step.

    ``status``/``saved_by``/``saved_at`` are optional provenance for the header; the
    caller passes them when exporting a saved worksheet so the document identifies itself.
    """
    out = [
        f"# Investment analysis — {ticker}",
        "",
        f"Generated from the worksheet (schema version {payload.get('version', SCHEMA_VERSION)}).",
    ]
    provenance = [
        f"{label}: {value}"
        for label, value in (
            ("Status", status),
            ("Last saved by", saved_by),
            ("Last saved", saved_at),
        )
        if value
    ]
    if provenance:
        out.append("")
        out.extend(f"- {line}" for line in provenance)
    out.append("")
    for index, section in enumerate(SECTIONS, start=1):
        values = payload.get("sections", {}).get(section.id, {})
        out.append(f"## {index}. {section.title}")
        out.append("")
        if section.intro:
            out.append(f"_{section.intro}_")
            out.append("")
        for f in section.all_fields:
            if f.kind == "score":
                value = values.get(f.id)
                text = "" if value in (None, "") else str(value)
            else:
                text = str(values.get(f.id) or "").strip()
            if text in ("", PLACEHOLDER):
                continue
            if f.kind == "textarea" and "\n" in text:
                out.append(f"**{f.label}:**")
                out.append("")
                out.append(text)
                out.append("")
            else:
                out.append(f"**{f.label}:** {text}")
                out.append("")
        out.extend(_confidence_block(section, values))
        out.append("---")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _confidence_block(section: Section, values: dict) -> list[str]:
    if section.id == "final":
        level = values.get("confidence_overall") or "(unset)"
        reasons = [
            ("Data quality", "data_quality"),
            ("Forecast uncertainty", "forecast_uncertainty"),
            ("Sensitivity to assumptions", "sensitivity_assumptions"),
            ("Variant perception conviction", "variant_conviction"),
        ]
        block = ["```text", f"Confidence Level: {level}", "Reasons:"]
        for label, field_id in reasons:
            value = str(values.get(field_id) or "").strip() or "(unset)"
            block.append(f"- {label}: {value}")
        block += ["```", ""]
        return block
    if not section.has_confidence:
        return []
    level = values.get("confidence") or "(unset)"
    block = ["```text", f"Confidence Level: {level}"]
    note = str(values.get("confidence_note") or "").strip()
    if note:
        block.append(f"Reason: {note}")
    block += ["```", ""]
    return block


def diff_payloads(before: dict, after: dict) -> list[dict]:
    """Fields whose value changed between two worksheet payloads, in workflow order.

    Returned entries carry human labels and display strings, not raw payload values, so
    the caller can render a revision's changes without knowing the widget types. Selects
    and scores read the same way they are stored.
    """
    changes: list[dict] = []
    for section in SECTIONS:
        old_values = before.get("sections", {}).get(section.id, {})
        new_values = after.get("sections", {}).get(section.id, {})
        for f in section.all_fields:
            was = _display_value(old_values.get(f.id), f)
            now = _display_value(new_values.get(f.id), f)
            if was != now:
                changes.append(
                    {"section": section.title, "field": f.label, "before": was, "after": now}
                )
    return changes


def format_change(change: dict, width: int = 48) -> str:
    """One-line ``field: before -> after`` rendering of a :func:`diff_payloads` entry."""
    before = _shorten(change["before"], width) or "(empty)"
    after = _shorten(change["after"], width) or "(empty)"
    return f"{change['section']} / {change['field']}: {before} -> {after}"


def _display_value(raw, f: Field) -> str:
    if f.kind == "score":
        return "" if raw in (None, "") else str(raw)
    text = "" if raw is None else str(raw).strip()
    return "" if text == PLACEHOLDER else text


def _shorten(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"
