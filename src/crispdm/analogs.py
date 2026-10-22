"""Historical analogs: a cross-sectional base rate for setups like the current one.

The investment-analysis worksheet asks what a setup like today's turned into. The
honest answer is a *rate over a population* -- "when the sector's payers were at
this yield with this coverage, 64% of the next twelve months were positive" -- and
not a lookback at one security's own history, which answers a different question
("how has this one security gone, which is partly luck and mostly its own past).

Three things make the number trustworthy, and each one is a decision rather than a
default.

**The conditions are read as they were, not as they are.** The similarity filter
compares today's yield and coverage against the conditions recorded at each
*historical* observation date, so a peer that matched in 2019 is matched on what
was true in 2019. Scoring a 2019 peer by today's conditions would match a setup
that never existed.

**The sample is a cross-section, not a time series of one name.** The peer set is
the target's industry, so a base rate for a regional bank is built from regional
banks, and one for a midstream partnership from midstream partnerships.

**The sample is thin enough to be honest.** Forward 12M returns are almost
perfectly serially correlated: consecutive daily windows share 251 of their 252
observations, and the measured lag-1 autocorrelation is 0.994. Sampling every
trading day would report roughly ten times more "observations" than there are
statistically independent ones, and a base rate whose confidence looks far stronger
than it is. The engine therefore samples the first observation date of each month,
which is the finest grid of non-overlapping windows at this horizon.

The sample is *descriptive*. It says what happened to comparable setups in the
period it covers; it does not say what will happen to this one, and the worksheet
does not present it as a forecast. Two limits are carried in the result and shown
to the reader rather than hidden: the industry classification is a current snapshot
applied to historical dates, and a forward return is only knowable 252 trading days
after the fact, so the most recent year of setups is not yet scoreable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from . import returns

#: Conditions are compared within this relative band. A peer at twice the target's
#: yield is a different setup from one at the same yield, and the band has to be
#: wide enough to leave a usable sample and narrow enough to mean something.
#: At +/-50% the JNJ peer group keeps 211 of 1,680 observations.
SIMILARITY_BAND = 0.5

#: The minimum number of similar observations before a base rate is reported at
#: all. Below this the rate is one or two data points wearing a percentage, and a
#: percentage that looks precise is worse than an honest absence.
MIN_OBSERVATIONS = 30

#: A peer priced below this is excluded. Sub-penny and split-artifact prices make
#: the yield and coverage ratios meaningless, and the model's own price-quality
#: rules already classify them; excluding them keeps the sample to securities a
#: reader could actually have bought.
MIN_PRICE = 5.0

#: The price-quality verdict the model already assigns. Only 'ok' rows are used:
#: a 'split_artifact' row has a yield computed from a price that is 40,000x its own
#: median, and 'sub_penny' rows have a yield that is a rounding error.
PRICE_QUALITY_OK = "ok"

#: The base rate is a share of the sample, so it is stated as a percentage.
PERCENT = 100.0

#: Caveats shown with every base rate. These are properties of the data, not
#: editorial notes, and a reader who is not told them would read more into the
#: number than it supports.
LOOKAHEAD_CAVEAT = (
    "Peers are classified by today's industry, applied to historical dates; "
    "the industry taxonomy is a current snapshot, not a point-in-time one."
)

PREDICTIVE_CAVEAT = (
    "This is a descriptive rate over comparable setups in the period covered, "
    "not a validated forecast of the next twelve months."
)

LAG_CAVEAT = (
    "A forward twelve-month return is only knowable 252 trading days after the "
    "setup, so the most recent year of setups is not yet scoreable."
)


@dataclass(frozen=True)
class Setup:
    """One historical observation of a peer, and how it turned out."""

    as_of_date: object
    ticker: str
    industry: str
    dividend_yield: float | None
    dividend_coverage: float | None
    total_return: float
    price_return: float | None = None
    dividend_return: float | None = None

    @property
    def positive(self) -> bool:
        return self.total_return > 0

    @property
    def outcome(self) -> str:
        return "Positive" if self.positive else "Negative"


@dataclass(frozen=True)
class PeerGroup:
    """The wider peer group's outcome, for context around the base rate.

    "What happened to setups like this" is a narrower question than "what happened
    to this sector", and both answers are worth reading: the peer group says
    whether the sector was generally kind over the period, and the similar slice
    says whether the setups closest to today's were.
    """

    observations: int = 0
    pct_positive: float | None = None
    avg_return: float | None = None
    median_return: float | None = None
    p05_return: float | None = None
    p95_return: float | None = None


@dataclass(frozen=True)
class BaseRate:
    """The result of a base-rate query.

    The headline figures describe the SIMILAR sample: the peer observations whose
    recorded conditions matched the target's within the similarity band. That is
    what the worksheet's base-rate field reports, because the field's contract is
    "the percentage of similar conditions that produced a positive return". The
    wider peer group is carried in ``peer`` as context.
    """

    ticker: str
    industry: str | None
    as_of_date: object
    observations: int = 0
    pct_positive: float | None = None
    avg_return: float | None = None
    median_return: float | None = None
    p05_return: float | None = None
    p95_return: float | None = None
    similar: list[Setup] = field(default_factory=list)
    peer: PeerGroup = field(default_factory=PeerGroup)
    caveats: list[str] = field(default_factory=list)
    current_yield: float | None = None
    current_coverage: float | None = None

    @property
    def has_sample(self) -> bool:
        return self.observations >= MIN_OBSERVATIONS

    @property
    def base_rate_text(self) -> str:
        """The rate as the worksheet's single-percentage field requires.

        The schema validates this field to exactly one number between 0 and 100,
        so the count and the caveats travel in the implication field instead.
        """
        if self.pct_positive is None:
            return ""
        return f"{self.pct_positive:.0f}%"


#: The base-rate query.
#:
#: ``monthly`` groups the stored forward-return dates by calendar month and
#: ``snapshots`` takes the earliest of each, so the sample is non-overlapping
#: rather than 252-times correlated (see the module docstring).
#:
#: ``sample`` joins each forward return to the features recorded on the SAME date,
#: so a peer is scored on the conditions that held then. The forward return comes
#: from model.forward_returns, which holds only complete 252-observation windows.
#:
#: The quality filter mirrors the model's own price-quality rules: a row whose
#: price was classified as a split artifact or a sub-penny value has a yield that
#: is not a yield, and including it would let an unusable denominator into the
#: similarity filter.
def _monthly_sample_sql():
    """The base-rate SQL, with the monthly snapshot rule applied."""
    return """
WITH monthly AS (
  SELECT as_of_date, date_trunc('month', as_of_date) AS month_start
  FROM model.forward_returns
  WHERE as_of_date >= :date_from AND as_of_date < :date_to
  GROUP BY 1, 2
),
snapshots AS (
  SELECT min(as_of_date) AS as_of_date, month_start FROM monthly GROUP BY 2
),
sample AS (
  SELECT fr.as_of_date, rs.ticker, tp.industry,
         ft.dividend_yield, ft.dividend_coverage,
         fr.total_return, fr.price_return, fr.dividend_return
  FROM snapshots sn
  JOIN model.forward_returns fr ON fr.as_of_date = sn.as_of_date
  JOIN model.features ft
    ON ft.security_id = fr.security_id AND ft.as_of_date = fr.as_of_date
  JOIN clean.ticker_profile tp ON tp.security_id = fr.security_id
  JOIN reference.securities rs
    ON rs.security_id = fr.security_id AND rs.active
  WHERE tp.industry = :industry
    AND ft.price_quality = :price_quality
    AND ft.current_price >= :min_price
)
SELECT * FROM sample
"""


def peer_base_rate(
    query,
    security_id,
    as_of_date,
    *,
    ticker=None,
    date_from=None,
    date_to=None,
    band=SIMILARITY_BAND,
) -> BaseRate:
    """Compute the base rate for the industry the security belongs to.

    ``query`` is a callable of ``(sql, params)`` returning a frame, the shape
    ``app.ui.query`` and ``src.crispdm.db.read_df`` both provide.

    ``as_of_date`` is the date the target's current conditions are read from; the
    peer sample is scored against the conditions recorded at each historical date.
    """
    industry = _industry_of(query, security_id)
    if industry is None:
        return BaseRate(
            ticker=ticker or "",
            industry=None,
            as_of_date=as_of_date,
            caveats=[_no_industry_caveat()],
        )

    frame = query(
        _monthly_sample_sql(),
        {
            "industry": industry,
            "price_quality": PRICE_QUALITY_OK,
            "min_price": MIN_PRICE,
            "date_from": date_from or "1900-01-01",
            "date_to": date_to or "2999-12-31",
        },
    )

    sample = [
        Setup(
            as_of_date=row["as_of_date"],
            ticker=row["ticker"],
            industry=row["industry"],
            dividend_yield=_float(row["dividend_yield"]),
            dividend_coverage=_float(row["dividend_coverage"]),
            total_return=float(row["total_return"]),
            price_return=_float(row["price_return"]),
            dividend_return=_float(row["dividend_return"]),
        )
        for row in frame.to_dict("records")
    ]

    current = _current_conditions(query, security_id, as_of_date)
    similar = _similar(sample, current, band)

    caveats = [LOOKAHEAD_CAVEAT, PREDICTIVE_CAVEAT, LAG_CAVEAT]
    if current is None:
        caveats.append(
            "The target's own current yield and coverage are unavailable, so the "
            "sample is the whole peer group rather than the setups closest to it."
        )

    if not sample:
        return BaseRate(
            ticker=ticker or "",
            industry=industry,
            as_of_date=as_of_date,
            caveats=caveats,
        )

    # The peer group is the context; the similar slice is the answer. When the
    # target's own conditions are unknown there is no similar slice, and the
    # wider group stands in for it rather than the base rate being left empty.
    peer = _peer_group(sample)
    headline = similar if similar else sample
    if not similar and current is not None:
        caveats.append(
            "No peer observation matched the current conditions closely enough, so "
            "the base rate is the whole peer group rather than a matched sample."
        )

    returns = sorted(item.total_return for item in headline)
    return BaseRate(
        ticker=ticker or "",
        industry=industry,
        as_of_date=as_of_date,
        observations=len(returns),
        pct_positive=PERCENT * sum(1 for value in returns if value > 0) / len(returns),
        avg_return=sum(returns) / len(returns),
        median_return=_median(returns),
        p05_return=_percentile(returns, 0.05),
        p95_return=_percentile(returns, 0.95),
        similar=similar,
        peer=peer,
        caveats=caveats,
        current_yield=current[0] if current else None,
        current_coverage=current[1] if current else None,
    )


def peer_base_rate_for_ticker(query, ticker, as_of_date, **kwargs):
    """The base rate for a ticker, resolving its security id first.

    A ticker can map to more than one security (a preferred and a common share,
    say), so the common stock is preferred, and the result is empty rather than
    wrong if the ticker is unknown.
    """
    frame = query(
        "SELECT CAST(security_id AS text) AS security_id FROM reference.securities "
        "WHERE ticker = :t AND active "
        "ORDER BY (security_type = 'common_stock') DESC, security_id LIMIT 1",
        {"t": ticker},
    )
    if frame.empty:
        return BaseRate(
            ticker=ticker,
            industry=None,
            as_of_date=as_of_date,
            caveats=[_no_industry_caveat()],
        )
    return peer_base_rate(query, frame.iloc[0]["security_id"], as_of_date, ticker=ticker, **kwargs)


def _peer_group(sample):
    """The whole peer group's outcome distribution."""
    returns = sorted(item.total_return for item in sample)
    if not returns:
        return PeerGroup()
    return PeerGroup(
        observations=len(returns),
        pct_positive=PERCENT * sum(1 for value in returns if value > 0) / len(returns),
        avg_return=sum(returns) / len(returns),
        median_return=_median(returns),
        p05_return=_percentile(returns, 0.05),
        p95_return=_percentile(returns, 0.95),
    )


def _similar(sample, current, band):
    """The observations whose conditions match the target's, within the band.

    A condition that is NULL on either side cannot be compared, so it does not
    match: a peer with no recorded coverage is not a peer whose coverage was
    close to the target's, and treating it as one would quietly widen the band.
    """
    if current is None:
        return []
    yield_now, coverage_now = current
    matched = []
    for item in sample:
        if item.dividend_yield is None or item.dividend_coverage is None:
            continue
        if not _within(item.dividend_yield, yield_now, band):
            continue
        if not _within(item.dividend_coverage, coverage_now, band):
            continue
        matched.append(item)
    # Chronological, so the spread below reads as a timeline and the most recent
    # observation is last rather than wherever the query happened to return it.
    matched.sort(key=lambda item: (item.as_of_date, item.ticker))
    return matched


def _within(value, target, band):
    """True when ``value`` is within ``band`` of ``target`` in relative terms.

    Relative, not absolute, because a yield of 0.5% and one of 1.0% are as
    different as 5% and 10%: the question is whether the setup is comparable, and
    comparability scales with size. A target of zero has no meaningful relative
    band, so only an exact match counts.
    """
    if target is None or value is None:
        return False
    if target == 0:
        return value == 0
    return abs(value - target) <= abs(band * target)


def _industry_of(query, security_id):
    frame = query(
        "SELECT tp.industry FROM clean.ticker_profile tp "
        "JOIN reference.securities rs ON rs.security_id = tp.security_id "
        "WHERE tp.security_id = CAST(:sid AS uuid) AND rs.active "
        "ORDER BY tp.industry NULLS LAST LIMIT 1",
        {"sid": str(security_id)},
    )
    if frame.empty:
        return None
    return frame.iloc[0]["industry"]


def _current_conditions(query, security_id, as_of_date):
    """The target's yield and coverage at ``as_of_date``."""
    frame = query(
        "SELECT dividend_yield, dividend_coverage FROM model.features "
        "WHERE security_id = CAST(:sid AS uuid) AND as_of_date <= CAST(:d AS date) "
        "ORDER BY as_of_date DESC LIMIT 1",
        {"sid": str(security_id), "d": as_of_date},
    )
    if frame.empty:
        return None
    row = frame.iloc[0]
    yield_now = _float(row["dividend_yield"])
    coverage_now = _float(row["dividend_coverage"])
    if yield_now is None or coverage_now is None:
        return None
    return yield_now, coverage_now


def _no_industry_caveat():
    return (
        "No industry is recorded for this security, so no peer sample could be "
        "built; a peer base rate is unavailable."
    )


def _as_date(value):
    """A date from whatever the driver returned for a DATE column.

    A driver may hand back a ``datetime.date``, a ``pandas.Timestamp`` or a string,
    and the window arithmetic below needs something it can subtract.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def _float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values):
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def _percentile(values, fraction):
    """A linear-interpolation percentile, matching Postgres's percentile_cont."""
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = fraction * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _pct(value):
    return f"{value * PERCENT:.0f}%"


def _pct1(value):
    return f"{value * PERCENT:.1f}%"


def own_forward_returns(query, security_id, rows=3, min_gap_days=350):
    """This security's own last complete forward windows, newest first.

    The windows do not overlap: consecutive daily windows share 251 of their 252
    observations, so three windows one trading day apart are one observation seen
    three times. Each pick steps back at least ``min_gap_days`` from the last, which
    is roughly a trading year, so the three windows are three separate years.
    """
    frame = returns.forward_returns_for(security_id, query=query)
    if frame.empty:
        return []

    picked = []
    for row in frame.to_dict("records"):
        as_of = _as_date(row.get("as_of_date"))
        if as_of is None:
            continue
        if picked and (_as_date(picked[-1]["as_of_date"]) - as_of).days < min_gap_days:
            continue
        picked.append(row)
        if len(picked) >= rows:
            break
    return list(reversed(picked))


def own_history_table(rows):
    """The own-history markdown table, from the materialised forward returns.

    The same table the peer path is built from, so the fallback is measured the
    same way as the answer it stands in for.
    """
    header = "| Period | Conditions | Forward 12M total return | Outcome |"
    divider = "| --- | --- | --- | --- |"
    if not rows:
        return "\n".join(
            [
                header,
                divider,
                "| not available | No completed forward window was stored | N/A | Unknown |",
            ]
        )
    lines = []
    for row in rows:
        value = _float(row.get("total_return"))
        if value is None:
            continue
        outcome = "Positive" if value > 0 else "Negative"
        lines.append(
            f"| {row['as_of_date']} to {row['forward_date']} | "
            f"Same security, 12M total-return window | {_pct1(value)} | {outcome} |"
        )
    if not lines:
        return "\n".join(
            [
                header,
                divider,
                "| not available | No completed forward window was stored | N/A | Unknown |",
            ]
        )
    return "\n".join([header, divider, *lines])


def base_rate_payload(base_rate, rows=6):
    """The base rate as plain data, for a worksheet builder or a JSON payload.

    The worksheet's own fields are strings, and the base-rate field is validated to
    hold exactly one percentage, so the count, the distribution and the caveats are
    carried alongside as separate keys rather than packed into that field.
    """
    return {
        "ticker": base_rate.ticker,
        "industry": base_rate.industry,
        "as_of_date": base_rate.as_of_date,
        "observations": base_rate.observations,
        "has_sample": base_rate.has_sample,
        "pct_positive": base_rate.pct_positive,
        "base_rate": base_rate.base_rate_text,
        "avg_return": base_rate.avg_return,
        "median_return": base_rate.median_return,
        "p05_return": base_rate.p05_return,
        "p95_return": base_rate.p95_return,
        "peer_observations": base_rate.peer.observations,
        "peer_pct_positive": base_rate.peer.pct_positive,
        "peer_median_return": base_rate.peer.median_return,
        "similar_table": similar_setups_table(base_rate, rows=rows),
        "caveats": list(base_rate.caveats),
        "current_yield": base_rate.current_yield,
        "current_coverage": base_rate.current_coverage,
    }


def similar_setups_table(base_rate, rows=6):
    """The markdown table the worksheet's ``similar_setups`` field carries.

    The contract is "date, conditions, forward 12M total return, outcome (3+ rows)".
    The rows are spread across the sample rather than taken from its end, so the
    table shows the range of outcomes instead of the most recent run of them; a
    table of the last six observations would read as a trend that the sample
    does not necessarily contain.
    """
    header = "| Date | Conditions | Forward 12M total return | Outcome |"
    divider = "| --- | --- | --- | --- |"
    if not base_rate.similar:
        return "\n".join(
            [
                header,
                divider,
                "| not available | No peer setup matched the current conditions | N/A | Unknown |",
            ]
        )

    chosen = _spread(base_rate.similar, rows)
    lines = []
    for item in chosen:
        conditions = _conditions_text(item)
        lines.append(
            f"| {item.as_of_date} | {conditions} | {_pct1(item.total_return)} | {item.outcome} |"
        )
    return "\n".join([header, divider, *lines])


def _spread(items, count):
    """Pick up to ``count`` observations spread evenly across the sample.

    The sample is ordered oldest-first, so an even stride keeps the earliest and
    the latest and fills between them, rather than taking a contiguous run.
    """
    if len(items) <= count:
        return list(items)
    stride = (len(items) - 1) / (count - 1)
    picked = [items[int(round(index * stride))] for index in range(count)]
    # Rounding can repeat an index; keep the first occurrence of each.
    seen, unique = set(), []
    for item in picked:
        key = (item.as_of_date, item.ticker)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _conditions_text(item):
    """The conditions of one observation, as a short phrase."""
    parts = []
    if item.dividend_yield is not None:
        parts.append(f"yield {item.dividend_yield * PERCENT:.2f}%")
    if item.dividend_coverage is not None:
        parts.append(f"coverage {item.dividend_coverage:.2f}x")
    if not parts:
        return "peer setup, conditions not recorded"
    return f"{item.industry}, " + ", ".join(parts)
