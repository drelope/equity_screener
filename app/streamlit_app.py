import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.crispdm.db import read_df

st.set_page_config(page_title="Dividend Equity CRISP-DM", layout="wide")
st.title("Dividend Equity Decision System")
st.caption(
    "Income 25% | Sustainability 20% | Legal/Economic Rights 25% | Appreciation 15% | Risk 10% | Valuation 5%"
)

df = read_df("""
SELECT s.ticker,s.security_type,f.as_of_date,f.current_price,f.dividend_yield,
       f.dividend_growth,f.fcf_payout,f.dividend_coverage,
       f.debt_to_ebitda,f.interest_coverage,
       f.volatility_252d,sc.composite_score,sc.score_coverage
FROM model.features f
JOIN reference.securities s ON s.security_id=f.security_id
LEFT JOIN model.scores sc ON sc.security_id=f.security_id AND sc.as_of_date=f.as_of_date
WHERE f.as_of_date=(SELECT MAX(as_of_date) FROM model.features)
  AND s.active = TRUE
ORDER BY sc.composite_score DESC NULLS LAST
""")
if df.empty:
    st.warning("No data. Run ETL, feature engineering, and scoring first.")
    st.stop()

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Securities", len(df))
c2.metric(
    "Median Yield",
    f"{df.dividend_yield.median():.2%}" if df.dividend_yield.notna().any() else "N/A",
)
scored = df.composite_score.dropna()
c3.metric(
    f"Median Score ({len(scored)}/{len(df)} scored)",
    f"{scored.median():.2f}" if len(scored) else "N/A",
)
# Coverage is the share of the measurable weight behind the composite. The
# median is shown because the mean would be dragged down by the deliberately
# unscored tail, and the count of unscored rows is what a reader needs to read
# the Median Score denominator above.
cov = df.score_coverage.dropna()
c4.metric(
    f"Median Coverage ({len(cov)}/{len(df)} scored)",
    f"{cov.median():.0%}" if len(cov) else "N/A",
)

# A blank ratio is ambiguous between "not computable" and "not yet built", and
# the two mean different things to a reader: the first is a property of the
# filer, the second is an unrun pipeline. Reporting the count beside the value
# separates them, so a column that is empty for every equity is visibly a
# pipeline gap rather than a sector of unremarkable companies.
d2e = df.debt_to_ebitda.dropna()
c5.metric(
    f"Median Debt/EBITDA ({len(d2e)}/{len(df)} reported)",
    f"{d2e.median():.2f}x" if len(d2e) else "N/A",
)
ic = df.interest_coverage.dropna()
c6.metric(
    f"Median Interest Cover ({len(ic)}/{len(df)} reported)",
    f"{ic.median():.2f}x" if len(ic) else "N/A",
)

y = st.slider("Minimum dividend yield", 0.0, 0.20, 0.02, 0.005)
types = st.multiselect(
    "Security type", sorted(df.security_type.unique()), default=sorted(df.security_type.unique())
)
v = df[(df.dividend_yield.fillna(0) >= y) & df.security_type.isin(types)]
st.dataframe(v, use_container_width=True, hide_index=True)
st.plotly_chart(
    px.scatter(
        v,
        x="dividend_yield",
        y="composite_score",
        hover_name="ticker",
        title="Dividend Yield vs Composite Score",
    ),
    use_container_width=True,
)
