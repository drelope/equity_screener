import pandas as pd

WEIGHTS = {
    "dividend_income_score": 0.25,
    "sustainability_score": 0.20,
    "legal_rights_score": 0.25,
    "appreciation_score": 0.15,
    "risk_score": 0.10,
    "valuation_score": 0.05,
}


def pct(s, high=True):
    r = pd.to_numeric(s, errors="coerce").rank(pct=True)
    return r if high else 1 - r


def score(df):
    x = df.copy()
    x["dividend_income_score"] = pct(x.dividend_yield)
    x["sustainability_score"] = (
        pct(x.dividend_coverage) * 0.5
        + pct(x.dividend_growth) * 0.2
        + pct(x.fcf_payout, False) * 0.3
    )
    x["legal_rights_score"] = x.legal_rights_score.fillna(0.5)
    x["appreciation_score"] = pct(x.momentum_252d) * 0.6 + pct(x.momentum_63d) * 0.4
    x["risk_score"] = pct(x.volatility_252d, False)
    x["valuation_score"] = 0.5
    x["composite_score"] = sum(x[k] * w for k, w in WEIGHTS.items())
    return x


def predictions(
    scores,
    run_id,
    threshold=0.5,
    model_version="rule_scoring_v1",
    feature_version="features_v1",
    data_version="sec_xbrl_v1",
):
    """Derive model.predictions rows from model.scores.

    The rule-based scorer produces a percentile composite score, so the
    sustainable-dividend probability is the composite itself and the predicted
    class is the composite against ``threshold``. ``run_id`` is generated once
    per campaign so all rows share one immutable model run.
    """
    x = scores.copy()
    x["run_id"] = run_id
    x["probability"] = x["composite_score"].clip(0, 1)
    x["predicted_class"] = (x["composite_score"] >= threshold).astype(int)
    x["precision_threshold"] = threshold
    x["model_version"] = model_version
    x["feature_version"] = feature_version
    x["data_version"] = data_version
    x["as_of_date"] = x["as_of_date"] if "as_of_date" in x.columns else None
    return x


def rankings(scores, predictions_df=None):
    """Derive model.rankings rows from model.scores (rank by composite score)."""
    x = scores.copy()
    x["rank"] = x["composite_score"].rank(ascending=False, method="first").astype(int)
    if predictions_df is not None and "probability" in predictions_df.columns:
        probs = predictions_df[["security_id", "as_of_date", "probability"]]
        x = x.merge(probs, on=["security_id", "as_of_date"], how="left")
    else:
        x["probability"] = x["composite_score"].clip(0, 1)
    return x
