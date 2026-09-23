import uuid

from sqlalchemy import text

from src.crispdm.db import engine, read_df
from src.crispdm.scoring import predictions, rankings, score

df = read_df("""
SELECT f.*,s.ticker,s.security_type
FROM model.features f JOIN reference.securities s ON s.security_id=f.security_id
WHERE f.as_of_date=(SELECT MAX(as_of_date) FROM model.features)
""")
if df.empty:
    print("No model.features rows; run the ETL to produce market data first.")
    raise SystemExit(0)
x = score(df)
run_id = uuid.uuid4()
pred = predictions(x, run_id, threshold=0.5)
rank = rankings(x, pred)

with engine.begin() as c:
    for _, r in x.iterrows():
        c.execute(
            text("""
        INSERT INTO model.scores
        (security_id,as_of_date,dividend_income_score,sustainability_score,legal_rights_score,
         appreciation_score,risk_score,valuation_score,composite_score)
        VALUES(:sid,:dt,:di,:su,:lr,:ap,:ri,:va,:co)
        ON CONFLICT(security_id,as_of_date) DO UPDATE SET
        dividend_income_score=EXCLUDED.dividend_income_score,
        sustainability_score=EXCLUDED.sustainability_score,
        legal_rights_score=EXCLUDED.legal_rights_score,
        appreciation_score=EXCLUDED.appreciation_score,
        risk_score=EXCLUDED.risk_score,
        valuation_score=EXCLUDED.valuation_score,
        composite_score=EXCLUDED.composite_score
        """),
            {
                "sid": r.security_id,
                "dt": r.as_of_date,
                "di": r.dividend_income_score,
                "su": r.sustainability_score,
                "lr": r.legal_rights_score,
                "ap": r.appreciation_score,
                "ri": r.risk_score,
                "va": r.valuation_score,
                "co": r.composite_score,
            },
        )
    for _, r in pred.iterrows():
        c.execute(
            text("""
        INSERT INTO model.predictions
        (run_id,security_id,as_of_date,probability,predicted_class,precision_threshold,
         model_version,feature_version,data_version)
        VALUES(:run,:sid,:dt,:prob,:cls,:thr,:mv,:fv,:dv)
        ON CONFLICT(run_id,security_id,as_of_date) DO UPDATE SET
        probability=EXCLUDED.probability,
        predicted_class=EXCLUDED.predicted_class,
        precision_threshold=EXCLUDED.precision_threshold
        """),
            {
                "run": str(run_id),
                "sid": r.security_id,
                "dt": r.as_of_date,
                "prob": r.probability,
                "cls": int(r.predicted_class),
                "thr": r.precision_threshold,
                "mv": r.model_version,
                "fv": r.feature_version,
                "dv": r.data_version,
            },
        )
    for _, r in rank.iterrows():
        c.execute(
            text("""
        INSERT INTO model.rankings
        (security_id,as_of_date,rank,composite_score,probability)
        VALUES(:sid,:dt,:rank,:cs,:prob)
        ON CONFLICT(security_id,as_of_date) DO UPDATE SET
        rank=EXCLUDED.rank,
        composite_score=EXCLUDED.composite_score,
        probability=EXCLUDED.probability
        """),
            {
                "sid": r.security_id,
                "dt": r.as_of_date,
                "rank": int(r.rank),
                "cs": r.composite_score,
                "prob": r.probability,
            },
        )
out = (
    x[["ticker", "security_type", "composite_score"]]
    .sort_values("composite_score", ascending=False)
    .head(20)
)
print(out.to_string(index=False))
print(f"\nRun id: {run_id}")
