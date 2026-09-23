import streamlit as st
import plotly.express as px
from src.crispdm.db import read_df

st.set_page_config(page_title="Dividend Equity CRISP-DM",layout="wide")
st.title("Dividend Equity Decision System")
st.caption("Income 25% | Sustainability 20% | Legal/Economic Rights 25% | Appreciation 15% | Risk 10% | Valuation 5%")

df=read_df("""
SELECT s.ticker,s.security_type,f.as_of_date,f.current_price,f.dividend_yield,
       f.dividend_growth,f.fcf_payout,f.dividend_coverage,f.debt_to_ebitda,
       f.volatility_252d,sc.composite_score
FROM model.features f
JOIN reference.securities s ON s.security_id=f.security_id
LEFT JOIN model.scores sc ON sc.security_id=f.security_id AND sc.as_of_date=f.as_of_date
WHERE f.as_of_date=(SELECT MAX(as_of_date) FROM model.features)
ORDER BY sc.composite_score DESC NULLS LAST
""")
if df.empty:
    st.warning("No data. Run ETL, feature engineering, and scoring first."); st.stop()

c1,c2,c3=st.columns(3)
c1.metric("Securities",len(df))
c2.metric("Median Yield",f"{df.dividend_yield.median():.2%}" if df.dividend_yield.notna().any() else "N/A")
c3.metric("Median Score",f"{df.composite_score.median():.2f}" if df.composite_score.notna().any() else "N/A")

y=st.slider("Minimum dividend yield",0.0,0.20,0.02,0.005)
types=st.multiselect("Security type",sorted(df.security_type.unique()),default=sorted(df.security_type.unique()))
v=df[(df.dividend_yield.fillna(0)>=y)&df.security_type.isin(types)]
st.dataframe(v,use_container_width=True,hide_index=True)
st.plotly_chart(px.scatter(v,x="dividend_yield",y="composite_score",hover_name="ticker",
                           title="Dividend Yield vs Composite Score"),use_container_width=True)
