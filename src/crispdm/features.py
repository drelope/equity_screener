from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import text

from .db import engine, read_df

FEATURE_COLUMNS = (
    "security_id",
    "as_of_date",
    "current_price",
    "annual_dividend",
    "dividend_yield",
    "dividend_growth",
    "earnings_payout",
    "fcf_payout",
    "dividend_coverage",
    "eps_ttm_growth",
    "debt_to_ebitda",
    "interest_coverage",
    # V0016. The CVS needs a liquidity leg, and the evidence floor of
    # regime.py compute_cvs refuses to score a company without one. This is a
    # populated column the analyst and the regime layer read; it is NOT in
    # model.FEATURES, for the same reason debt_to_ebitda was not until V0012
    # proved the model could use it.
    "quick_liquidity",
    "refinancing_wall",
    # The raw debt balance, carried alongside the two ratios derived from it.
    # Circuit breakers C2 and C3 read it to decide whether a filer has
    # reportable debt instruments at all: without it, a firm that reports no
    # debt and a firm whose debt was never extracted are the same NULL, and the
    # fail-closed rule cannot tell them apart. Not in model.FEATURES -- it is
    # an input to the regime layer's precondition, not a model predictor.
    "debt",
    "volatility_252d",
    "momentum_252d",
    "momentum_63d",
    "target_sustainable_dividend",
    "price_quality",
    "price_quality_rule",
    "yield_exclusion_reason",
    "raw_current_price",
    "raw_annual_dividend",
    "raw_dividend_yield",
)

#: Retired from the feature set because the warehouse cannot support them.
#:
#: Dropping a column is not the same as leaving it NULL. A column with no
#: source is a placeholder that trains on imputed noise and inflates the
#: declared feature count; a column that is deliberately absent is a recorded
#: decision. Each entry states the specific missing input:
#:
#: - ``debt_to_ebitda``  -- RETIRED 2026-09-29, RESTORED. The reason given was
#:   "no D&A and no EBITDA anywhere in the schema". That was true of the
#:   materialised columns and false of the data: ``raw.companyfacts`` keeps the
#:   whole XBRL payload, and D&A resolves in 64% of stored filings (72%
#:   including the split-tag fallbacks). Restored via V0011/V0012.
#: - ``interest_coverage``  -- RETIRED 2026-09-29, RESTORED. Same story:
#:   "no interest expense line in any table" was true of the schema and not of
#:   the payload, where interest expense resolves in 69% of filings.
#: - ``liquidation_discount`` -- still retired, and it is a different kind of
#:   problem from the two above: it needs a liquidation preference, which is a
#:   preferred-stock concept, and the universe is 57% common_stock, for which
#:   the metric is undefined rather than unknown. V0011 adds
#:   ``shares_outstanding``, which makes equity value derivable from price, but
#:   that is a precondition for a different metric and no data source closes
#:   this gap.
#: - ``legal_rights_score`` -- still retired. preferred.contract_terms holds 2
#:   rows against 10,992 securities. Carries 25% of the composite weight, which
#:   ``scoring.score`` neutralises with ``fillna(0.5)``; the weight itself is a
#:   policy decision and is untouched.
#: - ``data_quality_score`` -- still retired. audit.data_quality is a two-date
#:   snapshot (2026-09-21, 2026-09-26), not a per-as_of_date series, so joining
#:   it to a feature row would either match nothing or leak today's score into
#:   every historical row.
#: Restoring two of the five is the honest split: the first two were retired on
#: an incorrect claim about the data, and the last three are retired because the
#: data genuinely does not support them.
RETIRED_FEATURES = {
    "liquidation_discount": "preferred-only concept; undefined for 57% common_stock",
    "legal_rights_score": "preferred.contract_terms has 2 of 10992 securities",
    "data_quality_score": "audit.data_quality is a 2-date snapshot, not a series",
}


INSERT_FEATURE = text("""
INSERT INTO model.features
    (security_id,as_of_date,current_price,annualized_dividend,dividend_yield,
     dividend_growth,earnings_payout,fcf_payout,dividend_coverage,
     eps_ttm_growth,debt,debt_to_ebitda,interest_coverage,quick_liquidity,
     refinancing_wall,volatility_252d,
     momentum_252d,momentum_63d,target_sustainable_dividend,price_quality,
     price_quality_rule,yield_exclusion_reason,raw_current_price,
     raw_annual_dividend,raw_dividend_yield)
VALUES (:security_id,:as_of_date,:current_price,:annualized_dividend,
     :dividend_yield,:dividend_growth,:earnings_payout,:fcf_payout,
     :dividend_coverage,:eps_ttm_growth,:debt,:debt_to_ebitda,:interest_coverage,
     :quick_liquidity,:refinancing_wall,:volatility_252d,:momentum_252d,:momentum_63d,
     :target_sustainable_dividend,:price_quality,
     :price_quality_rule,:yield_exclusion_reason,:raw_current_price,
     :raw_annual_dividend,:raw_dividend_yield)
ON CONFLICT(security_id,as_of_date) DO UPDATE SET
    current_price=EXCLUDED.current_price,
    annualized_dividend=EXCLUDED.annualized_dividend,
    dividend_yield=EXCLUDED.dividend_yield,
    dividend_growth=EXCLUDED.dividend_growth,
    earnings_payout=EXCLUDED.earnings_payout,
    fcf_payout=EXCLUDED.fcf_payout,
    dividend_coverage=EXCLUDED.dividend_coverage,
    eps_ttm_growth=EXCLUDED.eps_ttm_growth,
    debt_to_ebitda=EXCLUDED.debt_to_ebitda,
    interest_coverage=EXCLUDED.interest_coverage,
    debt=EXCLUDED.debt,
    quick_liquidity=EXCLUDED.quick_liquidity,
    refinancing_wall=EXCLUDED.refinancing_wall,
    volatility_252d=EXCLUDED.volatility_252d,
    momentum_252d=EXCLUDED.momentum_252d,
    momentum_63d=EXCLUDED.momentum_63d,
    price_quality=EXCLUDED.price_quality,
    price_quality_rule=EXCLUDED.price_quality_rule,
    yield_exclusion_reason=EXCLUDED.yield_exclusion_reason,
    raw_current_price=EXCLUDED.raw_current_price,
    raw_annual_dividend=EXCLUDED.raw_annual_dividend,
    raw_dividend_yield=EXCLUDED.raw_dividend_yield
""")

#: Rows per INSERT. The universe is millions of feature rows, and a per-row
#: execute (or one transaction holding all of them) is needlessly slow.
FEATURE_CHUNK_SIZE = 20_000

#: A dividend yield outside this band is a data defect, not an observation.
#:
#: The upper bound: filers tag the per-share concepts with the period's
#: aggregate dollars often enough that a "per share" dividend reaches $560
#: (CDZI) or $862.50 (SIGIP), and some splits leave prices in the cents, so
#: the tail runs to 6,000,000% (PNXP: $30 dividend on a $0.0005 price). No
#: genuine payer sustains 25%: the highest real common/preferred yields sit
#: near 10-15% (REITs, BDCs, utilities), and a 25%+ yield is a cut in
#: progress, not a screenable opportunity. The $1.00 SPACs legitimately
#: cluster at exactly 0.25 and are kept.
#:
#: The lower bound: providers backfill unadjusted history across reverse
#: splits, so a pre-split row carries the post-split price (BINI at
#: $1.02tn, WHLR at $250bn) and the ratio collapses toward zero. One part
#: per million is below any real dividend: the lowest genuine yield in the
#: stored universe is 2e-05. Both tails are NULLed rather than dropped so
#: the rows still carry price, volatility and momentum.
MIN_PLAUSIBLE_YIELD = 1e-06
MAX_PLAUSIBLE_YIELD = 0.25

#: Columns whose values are a ratio of a per-share dividend to a share price
#: and are therefore only as trustworthy as both inputs.
RATIO_COLUMNS = ("annual_dividend", "dividend_yield")

#: A price below this cannot serve as a yield denominator. At $0.10 one cent
#: tick is 0.1% of the price, so the ratio still carries signal; below it the
#: tick dominates. The band under the floor is real, traded stock -- the
#: genuine $0.014 shell, GNOLF and GTCH at $0.00004 where a single tick is
#: 1000% of the price -- and the dividends there are fractions of a cent
#: ($0.001-$0.003), so the quotient is quantisation noise rather than an
#: economic quantity. This is an exclusion of an unusable denominator, not a
#: claim that the observation is false: the raw price is kept alongside it.
MIN_DENOMINATOR_PRICE = 0.10

#: How far a price may sit from its own security's median before it is
#: treated as a split-adjustment artifact. Providers backfill unadjusted
#: history across reverse splits, so a pre-split row carries a
#: post-split-scale price (BINI at $1.02tn against a $1.50 median).
#:
#: This is deliberately relative rather than a global dollar ceiling, because
#: no absolute ceiling separates an artifact from a genuinely expensive share:
#: BRK-A really does trade near $809,000 and PAVS near $490,000, and both
#: must survive. A ratio to the security's own history separates them
#: cleanly -- the artifacts are 40,000x-680,000x their own median, while
#: BRK-A never exceeds 1x and PAVS 4x. 50x leaves ample headroom for genuine
#: multi-decade appreciation.
SPLIT_ARTIFACT_RATIO = 50.0

PRICE_QUALITY_OK = "ok"
PRICE_QUALITY_SPLIT_ARTIFACT = "split_artifact"
PRICE_QUALITY_SUB_PENNY = "sub_penny"

RULE_SUB_PENNY = "price_below_floor"
RULE_SPLIT_ARTIFACT = "price_gt_50x_own_median"

#: Ratio-bound exclusions. These name the yield, not the price, because a
#: yield can be impossible for a good price (a numerator reported in whole
#: dollars per share rather than dollars per share).
RULE_YIELD_ABOVE_MAX = "yield_above_max"
RULE_YIELD_BELOW_MIN = "yield_below_min"


def db_value(value):
    """Return a value psycopg can store, mapping pandas missing values to NULL.

    Postgres ``numeric`` happily stores NaN, but a stored NaN is a real value
    that sorts above every other number and poisons AVG/MIN downstream, so
    missing data has to be written as SQL NULL. The label column is ``integer``
    and rejects NaN outright ("integer out of range").
    """
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def null_implausible_yields(df, low=MIN_PLAUSIBLE_YIELD, high=MAX_PLAUSIBLE_YIELD):
    """NULL the dividend ratio columns on rows whose yield is impossible.

    A yield outside ``[low, high]`` means at least one input is corrupt, so
    ``annual_dividend`` is nulled alongside ``dividend_yield``: the per-share
    amount is what carries the unit error, and leaving it would let any later
    consumer recompute the same bad ratio. The row itself survives, so price,
    volatility and momentum are still available.

    This is a bound on the *ratio* and deliberately says nothing about which
    input is at fault; ``classify_price_quality`` is what identifies a bad
    denominator. Keeping the two separate is what stops a split artifact from
    being reported as a dividend-calculation error.

    Because this is a ratio bound and not a verdict on either input, it records
    its own reason in ``yield_exclusion_reason`` rather than overloading
    ``price_quality_rule``. A row can be excluded for an out-of-range yield
    while its price is perfectly good -- CDZI's $560/share is a numerator unit
    error -- and collapsing the two would misattribute that to the price.
    """
    if df.empty or "dividend_yield" not in df.columns:
        return df
    out = df.copy()
    bad = ~out["dividend_yield"].between(low, high, inclusive="both")
    # An absent yield is missing data, not an impossible one: leave it NULL
    # rather than counting it as a defect.
    for column in RATIO_COLUMNS:
        if column in out.columns:
            out.loc[bad, column] = np.nan
    # The reason is read from the pre-filter yield. capture_raw_observations
    # has normally run already, but fall back to the live column so this
    # function stays correct when called on its own.
    observed = (
        out["raw_dividend_yield"] if "raw_dividend_yield" in out.columns else out["dividend_yield"]
    )
    reason = pd.Series(pd.NA, index=out.index, dtype=object)
    reason[bad & (observed > high)] = RULE_YIELD_ABOVE_MAX
    reason[bad & observed.notna() & (observed < low)] = RULE_YIELD_BELOW_MIN
    out["yield_exclusion_reason"] = reason
    return out


#: Interest must be at least this fraction of revenue to count as a real cost.
#:
#: 0.5% is deliberately low: the floor exists to catch a netted residual, not to
#: express a view about how much interest a company should carry. Raising it
#: starts rejecting genuine coverage on thin-but-real interest lines, which is
#: the error the floor was added to avoid.
interest_materiality_floor = 0.005


def earnings_growth(df):
    """Add ``eps_ttm_growth`` -- current TTM against prior TTM earnings.

    Negative growth is a classic pre-cut signal: a company whose earnings are
    shrinking is less likely to sustain, let alone grow, its dividend. The
    divisor is guarded so a negative or zero prior base cannot produce a
    misleading ratio -- ``5.0 / -3.0 - 1`` is ``-2.67``, which is a number
    arithmetic is happy to return and a reader would reasonably believe. The
    sign flip is the real hazard: a loss-to-profit recovery computes as
    strongly *negative* growth, so a company that just turned around would rank
    as the most deteriorating in the universe.

    Split out from ``build_features`` for the same reason ``leverage_ratios``
    is: the arithmetic is worth testing without the ~300-line query that
    produces its inputs, and this one has a guard that is easy to regress.
    """
    x = df.copy()
    if "eps_ttm_prior" not in x.columns:
        x["eps_ttm_prior"] = np.nan
    prior = x["eps_ttm_prior"]
    x["eps_ttm_growth"] = (x["eps_ttm"] / prior.where(prior > 0) - 1).where(prior > 0)
    return x


def leverage_ratios(df):
    """Add ``debt_to_ebitda`` and ``interest_coverage`` to a feature frame.

    Both are undefined rather than merely large or small when a denominator is
    not a number, and the two failure modes are kept distinct on purpose:

    * **EBITDA <= 0** -- a company losing money at the operating line before
      D&A. That is a real adverse signal, but the ratio is undefined. Clamping
      it to a large number would file it in the same bucket as a genuinely
      20x-levered company, turning "cannot service any debt" into "very
      levered".
    * **No interest expense reported** -- a filer that folds interest into
      another line. Reading that as zero interest yields infinite coverage, the
      single most favourable value the column can take, awarded for missing
      data.

    Note the asymmetry, which is deliberate: interest coverage keeps a *negative*
    result. Negative EBIT is not an undefined ratio, it is a definite answer to
    "does operating income service interest" -- no, and by how much -- and
    dropping it would leave the most distressed companies as the ones with no
    data. Only the denominator has to be a real, positive cost for the quotient
    to mean anything; an issuer whose net interest position is income rather
    than expense has no coverage ratio, and is left NULL rather than negative.

    In both NULL cases the earnings, coverage and yield features carry the
    distress signal, and the completeness audit reports the resulting sparsity
    rather than hiding it.

    Split out from ``build_features`` so the arithmetic is testable without the
    ~300-line query that produces its inputs. A column the caller does not have
    is treated as absent rather than raising: for a ratio, "no such input" and
    "the input is NULL" mean the same thing, and both mean the ratio is not
    computable.
    """
    x = df.copy()
    missing = [c for c in ("oi_ttm", "da_ttm", "int_ttm", "debt", "rev_ttm") if c not in x.columns]
    for column in missing:
        x[column] = np.nan
    operating_income = x["oi_ttm"]
    ebitda = operating_income + x["da_ttm"]
    x["debt_to_ebitda"] = x["debt"] / ebitda.where(ebitda > 0)
    interest = x["int_ttm"]
    # Interest has to be a real cost before dividing by it says anything. It is
    # not enough for the reported number to be positive: investment companies
    # report interest *netted* against interest income, so the line is a small
    # residual rather than an expense, and EBIT divided by a residual produces
    # arithmetic rather than economics. Measured on the latest date that
    # admitted 11.4% of coverage ratios, with a range of -3,076,000 to 40,225,
    # 160 rows above 100x, and negative per-security-type means.
    #
    # The floor is relative to revenue rather than an absolute dollar amount,
    # because the universe spans closed-end funds and preferred issues through to
    # the large caps: a fixed threshold is trivial for one and prohibitive for
    # the other. Revenue is the scale the interest line is judged against.
    #
    # The floor only *rejects*; it never rescues. A ratio whose denominator is
    # material stays as computed, including the negative ones, and a filer that
    # reports no revenue is left alone because there is nothing to be immaterial
    # *relative to*.
    denominator = interest.where(interest > 0)
    material = x["rev_ttm"].isna() | (
        interest.abs() >= interest_materiality_floor * x["rev_ttm"].abs()
    )
    x["interest_coverage"] = operating_income / denominator.where(material)
    return x


def capture_raw_observations(df, price_column="current_price"):
    """Copy the unfiltered per-share inputs into ``raw_*`` audit columns.

    Must run before any filter. Both ``raw_current_price`` and
    ``raw_dividend_yield`` are the evidence that an excluded row was excluded:
    once ``dividend_yield`` has been NULLed the original ratio is unrecoverable
    from the feature table, and an excluded row with no recorded input cannot
    be audited or reproduced.
    """
    if df.empty:
        return df
    out = df.copy()
    out["raw_current_price"] = out[price_column] if price_column in out.columns else np.nan
    if "dividend_yield" in out.columns:
        out["raw_dividend_yield"] = out["dividend_yield"]
    if "annual_dividend" in out.columns:
        out["raw_annual_dividend"] = out["annual_dividend"]
    return out


def classify_price_quality(
    df,
    floor=MIN_DENOMINATOR_PRICE,
    ratio=SPLIT_ARTIFACT_RATIO,
    median_column="price_median",
    price_column="current_price",
):
    """Label each row's price as a usable or meaningless yield denominator.

    Adds ``price_quality`` / ``price_quality_rule``.

    The two rules are ordered cheapest-first and the sub-penny test wins ties,
    because a $0.00004 price is meaningless whether or not it is also
    inconsistent with its own history. A row with no usable price at all is
    left ``ok``: an absent denominator is missing data, and a NULL yield
    already prevents it from producing a ratio.
    """
    if df.empty:
        return df
    out = df.copy()

    quality = pd.Series(PRICE_QUALITY_OK, index=out.index, dtype=object)
    rule = pd.Series(pd.NA, index=out.index, dtype=object)

    price = pd.to_numeric(out[price_column], errors="coerce")
    usable = price.notna() & (price > 0)

    sub_penny = usable & (price < floor)
    quality[sub_penny] = PRICE_QUALITY_SUB_PENNY
    rule[sub_penny] = RULE_SUB_PENNY

    if median_column in out.columns:
        median = pd.to_numeric(out[median_column], errors="coerce")
        # Both price and median must be present and positive; a NULL median
        # means the security has too little history to judge, not that the
        # price is bad.
        comparable = usable & median.notna() & (median > 0)
        artifact = comparable & (price / median > ratio) & (quality == PRICE_QUALITY_OK)
        quality[artifact] = PRICE_QUALITY_SPLIT_ARTIFACT
        rule[artifact] = RULE_SPLIT_ARTIFACT

    out["price_quality"] = quality
    out["price_quality_rule"] = rule
    return out


def apply_price_quality(df, floor=MIN_DENOMINATOR_PRICE, ratio=SPLIT_ARTIFACT_RATIO):
    """Classify price quality, then void the ratio on an unusable denominator.

    An unusable denominator makes the ratio meaningless regardless of the
    dividend, so the yield and the amount are NULLed on those rows -- but
    only after the raw observation has been preserved, so the exclusion stays
    reviewable. Order matters: this runs after the raw_* capture inside
    ``classify_price_quality`` and after the ratio bounds, so the audit
    columns hold what the provider actually said.
    """
    out = classify_price_quality(df, floor=floor, ratio=ratio)
    if out.empty or "price_quality" not in out.columns:
        return out
    bad = out["price_quality"] != PRICE_QUALITY_OK
    for column in RATIO_COLUMNS:
        if column in out.columns:
            out.loc[bad, column] = np.nan
    return out


def build_features(date_from=None, date_to=None):
    """Build the feature table, optionally for one observation-date window.

    The window exists because the query's peak memory is set by the quarterly
    TTM join, which resolves one row per (security, observation date, period) for
    every quarter the filer has ever reported. Across the full 2019-2026 history
    that intermediate reached roughly 60M rows and the build exhausted a 15 GB
    host: making the vintage chain per-metric, so a label that omits a metric no
    longer masks a published one, unions the two metric streams and doubled that
    intermediate. The feature rows themselves are only about 1.2M per year.

    Bounding the window bounds the intermediate, and so the peak. Trailing
    features are unaffected because the price window functions upstream still
    see the full history -- only the vintages and the output are bounded, never
    the LAG and volatility calculations that need prior prices.
    """
    sql = """
    WITH r AS (
      SELECT security_id, observation_date, close,
        LAG(close,63) OVER w p63,
        LAG(close,252) OVER w p252,
        LN(close/NULLIF(LAG(close) OVER w,0)) daily_return
      FROM raw.market_data WHERE close IS NOT NULL
      WINDOW w AS (PARTITION BY security_id ORDER BY observation_date)
    ),
    p AS (
      -- daily_vol must be earned, not assumed. STDDEV_SAMP returns a number
      -- from two samples, so without the sample-count guard volatility_252d
      -- was populated from 3 observations and annualised by sqrt(252) -- a
      -- value that is not a 252-day volatility at all. Require a full window.
      SELECT security_id, observation_date, close, p63, p252,
        COUNT(daily_return) OVER v AS vol_samples,
        STDDEV_SAMP(daily_return) OVER v AS daily_vol
      FROM r
      WINDOW v AS (PARTITION BY security_id ORDER BY observation_date
             ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
    ),
    d AS (
      SELECT security_id, ex_dividend_date, amount, provider, frequency
      FROM raw.dividend_data
      WHERE amount > 0
        AND (provider <> 'SEC_XBRL' OR concept IN (
              'CommonStockDividendsPerShareDeclared',
              'CommonStockDividendsPerShareCashPaid',
              'PreferredStockDividendsPerShareDeclared'))
    ),
    -- One annual dividend per (security, as_of_date), never a sum across
    -- providers: XBRL reports an annual per-share total while OpenBB reports
    -- the individual payments, so adding them double counts a payer that both
    -- sources cover. The payment series wins because it is per-payment and
    -- fresher; the latest declaration is the fallback where OpenBB is silent.
    d_paid AS (
      SELECT p.security_id, p.observation_date, SUM(d.amount) AS annual_dividend
      FROM p JOIN d
        ON d.security_id = p.security_id
       AND d.provider = 'OPENBB'
       AND d.ex_dividend_date BETWEEN p.observation_date - INTERVAL '365 days'
                                 AND p.observation_date
      GROUP BY 1, 2
    ),
    d_declared AS (
      SELECT DISTINCT ON (p.security_id, p.observation_date)
             p.security_id, p.observation_date, d.amount AS annual_dividend
      FROM p JOIN d
        ON d.security_id = p.security_id
       AND d.provider <> 'OPENBB'
       AND d.ex_dividend_date <= p.observation_date
      ORDER BY p.security_id, p.observation_date, d.ex_dividend_date DESC
    ),
    -- Prior-year dividend, for growth.
    --
    -- Two sources, because neither alone spans the history. The per-payment
    -- OPENBB series only starts 2025-01-02, so a trailing-365-day comparison
    -- against it is undefined for every labelled row (all of which end
    -- 2025-09-25) and would leave dividend_growth at zero coverage exactly
    -- where the model needs it. The SEC XBRL annual series reaches back to
    -- 2007, so it supplies the prior year.
    --
    -- The two are compared on the same basis within each source: two trailing
    -- 365-day payment windows for OPENBB, and the two most recent annual
    -- declarations for XBRL. They are never mixed, so a growth figure is
    -- always like-for-like. The OPENBB path is preferred because a payment
    -- series is fresher than an annual declaration.
    d_prior_paid AS (
      SELECT p.security_id, p.observation_date, SUM(d.amount) AS prior_dividend
      FROM (SELECT DISTINCT security_id, observation_date FROM raw.market_data
            WHERE close IS NOT NULL
              AND observation_date >= :date_from AND observation_date < :date_to) p
      JOIN d
        ON d.security_id = p.security_id
       AND d.provider = 'OPENBB'
       AND d.ex_dividend_date BETWEEN p.observation_date - INTERVAL '730 days'
                                  AND p.observation_date - INTERVAL '365 days'
      GROUP BY 1, 2
    ),
    d_paid_prior_window AS (
      SELECT p.security_id, p.observation_date, SUM(d.amount) AS current_dividend
      FROM (SELECT DISTINCT security_id, observation_date FROM raw.market_data
            WHERE close IS NOT NULL
              AND observation_date >= :date_from AND observation_date < :date_to) p
      JOIN d
        ON d.security_id = p.security_id
       AND d.provider = 'OPENBB'
       AND d.ex_dividend_date BETWEEN p.observation_date - INTERVAL '365 days'
                                  AND p.observation_date
      GROUP BY 1, 2
    ),
    d_annual AS (
      SELECT p.security_id, p.observation_date, d.ex_dividend_date, d.amount,
             ROW_NUMBER() OVER (PARTITION BY p.security_id, p.observation_date
                                ORDER BY d.ex_dividend_date DESC) rn
      FROM (SELECT DISTINCT security_id, observation_date FROM raw.market_data
            WHERE close IS NOT NULL
              AND observation_date >= :date_from AND observation_date < :date_to) p
      JOIN d
        ON d.security_id = p.security_id
       AND d.provider <> 'OPENBB'
       AND d.frequency = 'Annual'
       AND d.ex_dividend_date <= p.observation_date
    ),
    ann AS (
      SELECT security_id, observation_date,
             MAX(amount) FILTER (WHERE rn = 1) AS current,
             MAX(amount) FILTER (WHERE rn = 2) AS prior
      FROM d_annual
      GROUP BY 1, 2
    ),
    -- Each security's own median close, used as the reference for the
    -- split-artifact rule. A pre-reverse-split row backfilled unadjusted is
    -- orders of magnitude above its own median, while a genuinely expensive
    -- share (BRK-A near $809,000) sits at 1x its own median. Computed over
    -- the security's whole stored history rather than a trailing window so a
    -- young listing is still judged against something.
    med AS (
      SELECT security_id,
             percentile_cont(0.5) WITHIN GROUP (ORDER BY close) AS price_median
      FROM raw.market_data
      WHERE close IS NOT NULL AND close > 0
      GROUP BY 1
    ),
    -- Trailing-twelve-month fundamentals, point-in-time by filing date.
    --
    -- The join is on the filing date, NOT on period_end. A period is not
    -- available when it ends: the median gap from period_end to first filing is
    -- 37 days and p90 is 64, so period-end alignment fed the model a quarter's
    -- earnings before the issuer reported them. Measured across 200 stored
    -- payloads, 100% of periods were being matched before they were filed.
    --
    -- A period is also not a single fact. fundamentals.periodic_financials
    -- stores one row per (period, vintage): the original filing plus every
    -- later restatement, and 1,617 periods in a 300-payload sample carry more
    -- than one filing date. Each vintage therefore covers a half-open interval
    -- of observation dates, [filed, next_filed), built here with LEAD.
    --
    -- Expressing availability as an interval is what keeps this cheap *and*
    -- correct. The obvious alternative -- join on filed <= observation_date and
    -- pick the newest vintage with a window function -- matches every vintage of
    -- a period at once, so the window has to sort the whole market-history join
    -- (~250M rows) and the build runs out of memory. The interval form matches
    -- exactly one vintage per (security, period, observation_date) by
    -- construction, and confines the window function to the 1.2M-row
    -- fundamentals table.
    --
    -- Quarterly rows are summed over the four most recent periods; FY rows are
    -- the fallback for filers that do not break out quarters. Summing across a
    -- fiscal H1 would double count, so H1 is excluded from both paths.
    --
    -- A fiscal quarter must also occupy exactly one slot in that sum, and the
    -- fiscal_period label is not a safe key for it: 2,337 (security, period_end)
    -- pairs in the stored data carry more than one quarterly label, across 843
    -- issuers. Chaining vintages per (security, period_end, fiscal_period) gave
    -- each label its own independent interval, so two labels for the same
    -- quarter both matched one observation date and both were ranked into the
    -- four-quarter window -- the sum counted one quarter twice, for eps and free
    -- cash flow alike, and the tie on period_end left ROW_NUMBER's choice
    -- between them unstable between builds.
    --
    -- Collapsing the labels to one row per (security, period, filed) makes the
    -- vintage chain a property of the period rather than of the label that
    -- happened to report it. The interval then matches exactly one row per
    -- (security, period, observation date), which makes the four slots four
    -- distinct quarters and the ranking deterministic. Preferring a non-null
    -- figure first is what keeps a label that reports the period without a value
    -- from masking one that does.
    q_quarterly AS (
      SELECT DISTINCT ON (pf.security_id, pf.period_end, pf.filed)
             pf.security_id, pf.period_end, pf.filed, pf.eps, pf.free_cash_flow,
             pf.operating_income, pf.depreciation_amortization, pf.interest_expense,
             pf.revenue
      FROM fundamentals.periodic_financials pf
      WHERE pf.fiscal_period IN ('Q1', 'Q2', 'Q3', 'Q4')
      ORDER BY pf.security_id, pf.period_end, pf.filed,
               (pf.eps IS NULL), pf.fiscal_period
    ),
    -- Each metric gets its own chain, because "public" is a property of the
    -- metric and not of the period. The same period_end is labelled with more
    -- than one quarterly fiscal_period in 2,337 stored pairs across 843 issuers,
    -- and those labels disagree about what they report: merging them into one
    -- chain per period made a label that omitted EPS terminate the interval, and
    -- a period whose EPS had been published earlier then read as NULL from that
    -- date on. Measured over one quarter of observation dates, that discarded
    -- 5,755,484 of 9,456,567 resolvable slots -- 61% of the quarterly EPS the
    -- table actually holds, and the reason earnings_payout coverage sat near
    -- 68% while the underlying facts were far denser. Chaining only the
    -- vintages where a metric was actually reported keeps the last published
    -- figure in force until a later filing supersedes it, which is the same
    -- carry-forward rule the extractor documents, and resolves no slot to NULL.
    q_streams AS (
      SELECT security_id, period_end, filed, 'eps' AS metric, eps AS value
      FROM q_quarterly WHERE eps IS NOT NULL
      UNION ALL
      SELECT security_id, period_end, filed, 'fcf', free_cash_flow
      FROM q_quarterly WHERE free_cash_flow IS NOT NULL
      -- The leverage inputs join the same per-metric vintage chain as eps and
      -- fcf, for the same reason: each is ranked against the four most recent
      -- periods that reported *it*, so a filer disclosing D&A in all four
      -- quarters is not left with three because one quarter omitted the line
      -- while every quarter still reported EPS. Revenue travels the chain too,
      -- but as a threshold test rather than a feature.
      UNION ALL
      SELECT security_id, period_end, filed, 'oi', operating_income
      FROM q_quarterly WHERE operating_income IS NOT NULL
      UNION ALL
      SELECT security_id, period_end, filed, 'da', depreciation_amortization
      FROM q_quarterly WHERE depreciation_amortization IS NOT NULL
      UNION ALL
      SELECT security_id, period_end, filed, 'int', interest_expense
      FROM q_quarterly WHERE interest_expense IS NOT NULL
      UNION ALL
      SELECT security_id, period_end, filed, 'rev', revenue
      FROM q_quarterly WHERE revenue IS NOT NULL
    ),
    q_vintages AS (
      SELECT security_id, period_end, metric, filed, value,
             LEAD(filed) OVER (
               PARTITION BY security_id, period_end, metric
               ORDER BY filed) AS filed_next
      FROM q_streams
    ),
    -- Ranking per metric means the four slots are the four most recent periods
    -- that reported *that* metric, so eps_ttm and fcf_ttm may rest on different
    -- period sets. Forcing them onto one shared set would reintroduce the
    -- masking above for whichever metric a given filer reports less completely.
    q AS (
      SELECT security_id, observation_date,
             sum(value) FILTER (WHERE metric = 'eps' AND rn <= 4) eps_ttm,
             sum(value) FILTER (WHERE metric = 'eps' AND rn > 4 AND rn <= 8) eps_ttm_prior,
             sum(value) FILTER (WHERE metric = 'fcf' AND rn <= 4) fcf_ttm,
             sum(value) FILTER (WHERE metric = 'oi' AND rn <= 4) oi_ttm,
             sum(value) FILTER (WHERE metric = 'da' AND rn <= 4) da_ttm,
             sum(value) FILTER (WHERE metric = 'int' AND rn <= 4) int_ttm,
             sum(value) FILTER (WHERE metric = 'rev' AND rn <= 4) rev_ttm
      FROM (
        SELECT f.security_id, f.observation_date, v.metric, v.value,
               ROW_NUMBER() OVER (PARTITION BY f.security_id, f.observation_date, v.metric
                                  ORDER BY v.period_end DESC) rn
        FROM (SELECT DISTINCT security_id, observation_date FROM raw.market_data
              WHERE close IS NOT NULL
                AND observation_date >= :date_from AND observation_date < :date_to) f
        JOIN q_vintages v
          ON v.security_id = f.security_id
         AND f.observation_date >= v.filed
         AND (v.filed_next IS NULL OR f.observation_date < v.filed_next)
      ) z
      GROUP BY 1, 2
    ),
    fy_vintages AS (
      SELECT pf.security_id, pf.period_end, pf.filed,
             LEAD(pf.filed) OVER (
               PARTITION BY pf.security_id, pf.period_end
               ORDER BY pf.filed) AS filed_next,
             pf.eps, pf.free_cash_flow,
             pf.operating_income, pf.depreciation_amortization,
             pf.interest_expense, pf.revenue, pf.debt,
             pf.cash, pf.current_liabilities,
             pf.debt_maturing_12m, pf.debt_maturing_year_2,
             pf.committed_undrawn_facility
      FROM fundamentals.periodic_financials pf
      WHERE pf.fiscal_period = 'FY'
    ),
    fy AS (
      SELECT DISTINCT ON (f.security_id, f.observation_date)
             f.security_id, f.observation_date, v.period_end,
             v.eps AS eps_fy, v.free_cash_flow AS fcf_fy,
             v.operating_income AS oi_fy,
             v.depreciation_amortization AS da_fy,
             v.interest_expense AS int_fy,
             v.revenue AS rev_fy,
             v.debt AS debt_fy,
             v.cash AS cash_fy,
             v.current_liabilities AS current_liabilities_fy,
             v.debt_maturing_12m AS debt_maturing_12m_fy,
             v.debt_maturing_year_2 AS debt_maturing_year_2_fy,
             v.committed_undrawn_facility AS committed_undrawn_fy
      FROM (SELECT DISTINCT security_id, observation_date FROM raw.market_data
            WHERE close IS NOT NULL
              AND observation_date >= :date_from AND observation_date < :date_to) f
      JOIN fy_vintages v
        ON v.security_id = f.security_id
       AND f.observation_date >= v.filed
       AND (v.filed_next IS NULL OR f.observation_date < v.filed_next)
      ORDER BY f.security_id, f.observation_date, v.period_end DESC
    )
    SELECT p.security_id,p.observation_date as as_of_date,p.close current_price,
      COALESCE(d_paid.annual_dividend, d_declared.annual_dividend) AS annual_dividend,
      COALESCE(d_paid.annual_dividend, d_declared.annual_dividend)
        /NULLIF(p.close,0) dividend_yield,
      -- Growth needs a positive base on both sides; a rise from zero or a
      -- fall to zero is not a growth rate. Both sides of a comparison come
      -- from the same source so the basis matches.
      CASE WHEN d_prior_paid.prior_dividend > 0
           THEN d_paid_prior_window.current_dividend
                / d_prior_paid.prior_dividend - 1
           WHEN ann.current > 0 AND ann.prior > 0
           THEN ann.current / ann.prior - 1
      END dividend_growth,
      -- TTM basis, preferring four summed quarters and falling back to the
      -- last full year. NULLIF guards the divisor: a zero or negative
      -- earnings base makes a payout ratio meaningless, and a negative
      -- number here would read to the model as a favourable signal.
      COALESCE(q.eps_ttm, fy.eps_fy) eps_ttm,
      q.eps_ttm_prior,
      COALESCE(q.fcf_ttm,  fy.fcf_fy)  fcf_ttm,
      -- Same trailing-then-fallback basis for the leverage inputs. Debt is a
      -- balance, not a flow, so it is never summed across quarters: it is
      -- carried through the FY path and read as of the latest fiscal period
      -- that was public on the observation date, which is the same vintage
      -- discipline the flows get. A company with no FY row therefore has no
      -- debt figure here even when its quarterly rows exist -- an asymmetry
      -- recorded rather than papered over, because guessing a point-in-time
      -- balance from a flow table is the look-ahead this whole build avoids.
      COALESCE(q.oi_ttm,  fy.oi_fy)   oi_ttm,
      COALESCE(q.da_ttm,  fy.da_fy)   da_ttm,
      COALESCE(q.int_ttm, fy.int_fy)  int_ttm,
      COALESCE(q.rev_ttm, fy.rev_fy)  rev_ttm,
      fy.debt_fy debt,
      -- Quick liquidity: cash and short-term investments over obligations due
      -- within a year. Both legs are current-basis, taken from the FY vintage
      -- path on the same point-in-time discipline as debt -- a balance is read
      -- as of the latest fiscal period public on the observation date, never
      -- summed across quarters.
      --
      -- The denominator is guarded twice and both guards matter. A zero or
      -- negative current-liabilities figure means either a missing tag or a
      -- filer reporting a subtotal that does not reconcile; dividing by it
      -- yields a ratio no one should read. And current_liabilities is NULL for
      -- every row until the V0016 fundamentals rebuild runs, which is the
      -- honest state: the CVS evidence floor needs this leg, and a company
      -- cannot be shown to have liquidity we have not measured.
      --
      -- Cash is not coerced into being current-basis. A filer reporting only
      -- CashAndCashEquivalentsAtCarryingValue understates its own numerator
      -- here, which reads as slightly worse coverage rather than better --
      -- the direction section 4.1 wants, where a disclosure gap costs the
      -- filer instead of paying it.
      CASE WHEN fy.current_liabilities_fy > 0
           THEN fy.cash_fy / fy.current_liabilities_fy
      END quick_liquidity,
      -- Maturity cliff (circuit breaker C4): contractual principal falling due
      -- within 18 months over cash.
      --
      -- XBRL publishes the ladder in yearly buckets -- year one, then months
      -- 13-24 -- and C4 asks about 18 months, which lands inside year two.
      -- The half-year is a uniform-repayment assumption, and it is the only
      -- estimate in this column. A lumpy bullet maturity in month 13 makes the
      -- true figure up to twice the computed one; a schedule spread evenly
      -- makes it exact. The alternative, truncating to year one, would
      -- understate the cliff for every company whose debt repays on a
      -- schedule rather than a bullet, which is the more common shape and the
      -- more dangerous one to miss.
      --
      -- Year two is interpolated only when it is reported. Treating a missing
      -- year two as zero would invent a cliff of exactly 0.0 -- the best
      -- possible score on a 25%-weight metric -- for the 2,748 companies that
      -- disclose year one and stop. So a company without both buckets is left
      -- NULL, and the CVS evidence floor declines to guess.
      --
      -- Section 5.5 defines reserves as Cash plus Committed Undrawn Facilities,
      -- and 888 stored filers report a remaining borrowing capacity. Cash
      -- alone overstated the cliff on exactly the firms that hold a revolver
      -- next to a near-term maturity, so the facility is now included.
      --
      -- An undisclosed facility is not treated as zero capacity; it simply
      -- stays out of the numerator. Silence is not absence, and assuming
      -- otherwise would make the ratio *less* conservative, which is the wrong
      -- direction for a gate. A filer with no revolver and no tag therefore
      -- reads the same as before.
      CASE WHEN fy.cash_fy > 0
                 AND fy.debt_maturing_12m_fy IS NOT NULL
                 AND fy.debt_maturing_year_2_fy IS NOT NULL
           THEN (fy.debt_maturing_12m_fy + 0.5 * fy.debt_maturing_year_2_fy)
                / (fy.cash_fy + COALESCE(fy.committed_undrawn_fy, 0))
      END refinancing_wall,
      CASE WHEN p.p252>0 THEN p.close/p.p252-1 END momentum_252d,
      CASE WHEN p.p63>0 THEN p.close/p.p63-1 END momentum_63d,
      -- 252 trailing returns are required before this is a 252-day
      -- volatility; before that the sample count cannot support the claim.
      CASE WHEN p.vol_samples >= 252 THEN p.daily_vol*sqrt(252) END
        volatility_252d,
      med.price_median

    FROM p
    LEFT JOIN d_paid ON d_paid.security_id=p.security_id
                    AND d_paid.observation_date=p.observation_date
    LEFT JOIN d_declared ON d_declared.security_id=p.security_id
                         AND d_declared.observation_date=p.observation_date
    LEFT JOIN d_prior_paid ON d_prior_paid.security_id=p.security_id
                           AND d_prior_paid.observation_date=p.observation_date
    LEFT JOIN d_paid_prior_window ON d_paid_prior_window.security_id=p.security_id
                                AND d_paid_prior_window.observation_date=p.observation_date
    LEFT JOIN ann ON ann.security_id=p.security_id
                 AND ann.observation_date=p.observation_date
    LEFT JOIN q ON q.security_id=p.security_id
               AND q.observation_date=p.observation_date
    LEFT JOIN fy ON fy.security_id=p.security_id
                AND fy.observation_date=p.observation_date
    LEFT JOIN med ON med.security_id=p.security_id
    WHERE p.observation_date >= :date_from AND p.observation_date < :date_to
    """
    # An absent bound means "no bound", expressed as the full representable
    # range of the column so the same SQL text serves both the chunked and the
    # single-shot call.
    params = {
        "date_from": date_from or date.min,
        "date_to": date_to or date.max,
    }
    df = read_df(sql, params)
    annual = df["annual_dividend"]
    eps_ttm = df["eps_ttm"]
    fcf_ttm = df["fcf_ttm"]
    # Payout ratios are only defined against a positive denominator. A company
    # paying out of losses or negative cash flow has a real, adverse signal to
    # convey, but it is not a number; NULL says "not computable" while the
    # label and the yield features still carry the distress, and the
    # completeness audit reports the resulting sparsity rather than hiding it.
    df["earnings_payout"] = annual / eps_ttm.where(eps_ttm > 0)
    df["fcf_payout"] = annual / fcf_ttm.where(fcf_ttm > 0)
    # Coverage is the inverse: a null here means the earnings stream cannot
    # support the payout, which is the question the model is being asked.
    df["dividend_coverage"] = eps_ttm.where(eps_ttm > 0) / annual.where(annual > 0)
    df = earnings_growth(df)
    df = leverage_ratios(df)
    df["target_sustainable_dividend"] = np.nan
    df = df.replace([np.inf, -np.inf], np.nan)
    # Capture first, filter second. raw_* must hold the unfiltered inputs, so
    # any ordering that NULLs dividend_yield before the capture destroys the
    # only record of the value that was rejected.
    df = capture_raw_observations(df)
    # Ratio bounds and price quality are independent verdicts: a split
    # artifact is a bad denominator, a $560/share payout is a bad numerator,
    # and each keeps its own reason column.
    df = null_implausible_yields(df)
    return apply_price_quality(df)


#: Feature-frame column -> model.features column, where the two differ.
#:
#: The build query names the annualised total ``annual_dividend`` because that is
#: what the dividend CTE aggregates, while the stored column is
#: ``annualized_dividend``. The two lists were otherwise identical, and the
#: mismatch was invisible until execution: SQLAlchemy binds by name, so the
#: payload carried ``annual_dividend`` while the statement wanted
#: ``:annualized_dividend``, and every executemany raised "a value is required
#: for bind parameter 'annualized_dividend'". The row counts still matched, so
#: nothing about the schema hinted at it.
FEATURE_COLUMN_ALIASES = {"annual_dividend": "annualized_dividend"}


def feature_payload(df):
    """Return the feature rows as bind-parameter dicts, with NULLs for gaps."""
    records = df.to_dict(orient="records")
    return [
        {FEATURE_COLUMN_ALIASES.get(col, col): db_value(record.get(col)) for col in FEATURE_COLUMNS}
        for record in records
    ]


def persist_features(df, chunk_size=FEATURE_CHUNK_SIZE):
    if df.empty:
        return
    for start in range(0, len(df), chunk_size):
        payload = feature_payload(df.iloc[start : start + chunk_size])
        with engine.begin() as c:
            c.execute(INSERT_FEATURE, payload)
