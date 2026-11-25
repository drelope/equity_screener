"""Point-in-time (PIT) guard helpers (RM-01/RM-02, draft, schema-independent).

These utilities encode as-of and availability guard semantics without requiring
PIT schema migrations. They do not by themselves make historical universes or
features PIT-correct; they provide explicit contracts/hooks for code paths and
manifests while membership/timing storage remains incomplete.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

# Draft policy labels for manifests/evidence; not an approval or verified state.
PIT_POLICY_DRAFT = "pit_draft_v0"
UNIVERSE_ELIGIBILITY_MODE_DRAFT = "current_state_active_flag_with_as_of_scores"  # known limitation
FEATURE_TIMING_MODE_DRAFT = "filed_or_period_end_proxy"  # known leakage-risk proxy in places

# Consumer-specific draft timing/universe modes (RM-01/RM-02 integration, unverified).
FEATURE_BUILD_TIMING_MODE_DRAFT = "filed_or_period_end_proxy_greatest_draft"
FEATURE_WINDOW_UNIVERSE_MODE_DRAFT = "active_securities_feature_carry_forward_window_draft"
FEATURE_WINDOW_HISTORICAL_UNIVERSE_MODE_DRAFT = (
    "active_or_historical_securities_feature_carry_forward_window_draft"
)
FORWARD_RETURN_TIMING_MODE_DRAFT = "forward_return_realization_window_draft"
LABEL_OUTCOME_TIMING_MODE_DRAFT = "outcome_window_label_horizon_draft"
WALK_FORWARD_TIMING_MODE_DRAFT = "label_embargo_purge_D_plus_horizon_lt_test_start_draft"


def normalize_as_of(value: date | datetime | str | None) -> str | None:
    """Normalize an as-of value to ISO date string, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # validate ISO date
        return date.fromisoformat(s[:10]).isoformat()
    raise TypeError(f"unsupported as_of type: {type(value)!r}")


def require_as_of(value: date | datetime | str | None, *, context: str) -> str:
    """Require and normalize an as-of date for PIT-sensitive operations."""
    resolved = normalize_as_of(value)
    if resolved is None:
        raise ValueError(f"as_of is required for PIT-sensitive context: {context}")
    return resolved


def is_available_as_of(
    available_at: date | datetime | str | None, as_of: date | datetime | str | None
) -> bool | None:
    """Return True if available_at <= as_of, False if after, None if unknown.

    Unknown availability must not be treated as PIT-safe by callers; this helper
    only computes the comparison when both values are present.
    """
    if available_at is None or as_of is None:
        return None
    if isinstance(available_at, datetime):
        avail_d = available_at.date()
    elif isinstance(available_at, date):
        avail_d = available_at
    else:
        avail_d = date.fromisoformat(str(available_at)[:10])
    as_of_d = date.fromisoformat(normalize_as_of(as_of) or "9999-12-31")
    return avail_d <= as_of_d


def filing_period_availability_proxy(
    filed: date | str | None, period_end: date | str | None
) -> str | None:
    """Draft proxy availability date: max(filed, period_end) when both known.

    RM-02/FR-FEAT-01 context: using period_end before actual filing/acceptance
    availability can leak; using this proxy is not sufficient for verified PIT
    compliance. Returned as ISO date string or None.
    """
    if filed is None or period_end is None:
        return None
    filed_d = filed if isinstance(filed, date) else date.fromisoformat(str(filed)[:10])
    period_d = (
        period_end if isinstance(period_end, date) else date.fromisoformat(str(period_end)[:10])
    )
    return max(filed_d, period_d).isoformat()


def pit_manifest_metadata(
    *,
    as_of: date | datetime | str | None,
    universe_mode: str = UNIVERSE_ELIGIBILITY_MODE_DRAFT,
    feature_timing_mode: str = FEATURE_TIMING_MODE_DRAFT,
    notes: str | None = None,
) -> dict[str, Any]:
    """Manifest-friendly PIT metadata block (draft)."""
    return {
        "pit_policy": PIT_POLICY_DRAFT,
        "resolved_as_of": normalize_as_of(as_of),
        "universe_eligibility_mode": universe_mode,
        "feature_timing_mode": feature_timing_mode,
        "verified_pit_compliant": False,
        "notes": notes
        or "Draft PIT metadata only; membership history, availability timestamps, and leakage controls not fully implemented/verified.",
    }


def merge_pit_parameters(
    parameters: Mapping[str, Any] | None, as_of: Any = None, **extra: Any
) -> dict[str, Any]:
    out = dict(parameters or {})
    if "as_of" not in out and as_of is not None:
        out["as_of"] = normalize_as_of(as_of) if not isinstance(as_of, str) else as_of
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def feature_window_pit_context(
    *,
    as_of: date | datetime | str | None,
    carry_days: int | None = None,
    include_historical: bool = False,
) -> dict[str, Any]:
    """Draft PIT context for feature-window consumers (scoring/dashboard reads).

    Captures current carry-forward/active-flag behavior; not verified PIT-safe.
    """
    mode = (
        FEATURE_WINDOW_HISTORICAL_UNIVERSE_MODE_DRAFT
        if include_historical
        else FEATURE_WINDOW_UNIVERSE_MODE_DRAFT
    )
    return pit_manifest_metadata(
        as_of=as_of,
        universe_mode=mode,
        feature_timing_mode="feature_store_carry_forward_window_draft",
        notes=(
            "Draft PIT metadata: feature-window read uses latest row per security within carry-forward "
            "window anchored to as_of/max feature date and current reference.securities active/historical flags; "
            "membership/delisted history, availability timestamps, and PIT eligibility are not fully implemented or verified."
        ),
    ) | {
        "carry_days": carry_days,
        "include_historical": bool(include_historical),
    }


def walk_forward_pit_context(
    *, embargo_days: int | None = None, test_start: Any = None
) -> dict[str, Any]:
    """Draft PIT context for walk-forward/label evaluation consumers."""
    return pit_manifest_metadata(
        as_of=test_start,
        universe_mode="labeled_feature_rows_draft",
        feature_timing_mode=WALK_FORWARD_TIMING_MODE_DRAFT,
        notes=(
            "Draft PIT metadata: walk-forward purges training rows where label horizon reaches test period "
            "(D + horizon < test_start); does not by itself establish feature availability, universe PIT membership, "
            "or promotion-grade/holdout evidence."
        ),
    ) | {"embargo_days": embargo_days}
