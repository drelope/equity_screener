import numpy as np
from .db import read_df, engine
from sqlalchemy import text

def build_features():
    sql = """
    WITH p AS (
      SELECT security_id, observation_date, close,
        LAG(close,63) OVER(PARTITION BY security_id ORDER BY observation_date) p63,
        LAG(close,252) OVER(PARTITION BY security_id ORDER BY observation_date) p252,
        STDDEV_SAMP(LN(close/NULLIF(LAG(close) OVER
          (PARTITION BY security_id ORDER BY observation_date),0)))
          OVER(PARTITION BY security_id ORDER BY observation_date
               ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) daily_vol
      FROM raw.market_data WHERE close IS NOT NULL
    ),
    d AS (
      SELECT security_id, ex_dividend_date, amount,
        SUM(amount) OVER(PARTITION BY security_id ORDER BY ex_dividend_date
          RANGE BETWEEN INTERVAL '365 days' PRECEDING AND CURRENT ROW) annual_dividend
      FROM raw.dividend_data
    )
    SELECT p.security_id,p.observation_date as as_of_date,p.close current_price,
      d.annual_dividend,
      d.annual_dividend/NULLIF(p.close,0) dividend_yield,
      CASE WHEN p.p252>0 THEN p.close/p.p252-1 END momentum_252d,
      CASE WHEN p.p63>0 THEN p.close/p.p63-1 END momentum_63d,
      p.daily_vol*sqrt(252) volatility_252d
    FROM p
    LEFT JOIN LATERAL (
      SELECT annual_dividend FROM d
      WHERE d.security_id=p.security_id AND d.ex_dividend_date<=p.observation_date
      ORDER BY ex_dividend_date DESC LIMIT 1
    ) d ON TRUE
    """
    df=read_df(sql)
    for c in ["dividend_growth","earnings_payout","fcf_payout","dividend_coverage",
              "debt_to_ebitda","interest_coverage","liquidation_discount",
              "legal_rights_score","data_quality_score"]:
        df[c]=np.nan
    df["target_sustainable_dividend"]=np.nan
    return df.replace([np.inf,-np.inf],np.nan)

def persist_features(df):
    if df.empty: return
    cols=["security_id","as_of_date","current_price","annual_dividend","dividend_yield",
          "dividend_growth","earnings_payout","fcf_payout","dividend_coverage",
          "debt_to_ebitda","interest_coverage","volatility_252d","momentum_252d",
          "momentum_63d","liquidation_discount","legal_rights_score","data_quality_score",
          "target_sustainable_dividend"]
    with engine.begin() as c:
        for _,r in df.iterrows():
            p={x:r.get(x) for x in cols}
            c.execute(text("""
              INSERT INTO model.features
              (security_id,as_of_date,current_price,annualized_dividend,dividend_yield,
               dividend_growth,earnings_payout,fcf_payout,dividend_coverage,
               debt_to_ebitda,interest_coverage,volatility_252d,momentum_252d,
               momentum_63d,liquidation_discount,legal_rights_score,data_quality_score,
               target_sustainable_dividend)
              VALUES (:security_id,:as_of_date,:current_price,:annual_dividend,
               :dividend_yield,:dividend_growth,:earnings_payout,:fcf_payout,
               :dividend_coverage,:debt_to_ebitda,:interest_coverage,:volatility_252d,
               :momentum_252d,:momentum_63d,:liquidation_discount,:legal_rights_score,
               :data_quality_score,:target_sustainable_dividend)
              ON CONFLICT(security_id,as_of_date) DO UPDATE SET
               current_price=EXCLUDED.current_price,
               annualized_dividend=EXCLUDED.annualized_dividend,
               dividend_yield=EXCLUDED.dividend_yield,
               dividend_growth=EXCLUDED.dividend_growth,
               volatility_252d=EXCLUDED.volatility_252d,
               momentum_252d=EXCLUDED.momentum_252d,
               momentum_63d=EXCLUDED.momentum_63d
            """),p)
