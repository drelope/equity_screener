# Institutional Top-Down Investment Analysis — Workflow (v4)

Canonical reference for the investment-analysis workflow rendered by the Streamlit
**Investment analysis** page (`app/views/investment_analysis.py`).

**Source of truth:** the sections, field ids, types and option lists are defined in
`app/analysis_schema.py`. This document is written to match that module exactly; when
the two disagree, the code wins and this document is corrected. Field ids below are the
contract between this document, the worksheet form and the stored JSON payload
(`analysis.investment_analyses.payload`).

---

## Operating Rules

### Required workflow (sequential — do not skip steps)

1. Define the investment universe
2. Assess macro & credit conditions
3. Analyse the industry
4. Judge the capital cycle
5. Analyse the supply side
6. Analyse the demand side
7. Establish consensus expectations
8. Form a variant perception
9. Deep-dive the company
10. Assess earnings quality
11. Assess the competitive advantage (moat)
12. Assess management
13. Construct the valuation
14. Generate scenarios
15. Test against historical analogs
16. Decompose risk
17. Integrate with the portfolio
18. Reach a recommendation

**Hard constraint:** do not form conclusions (step 18) before data retrieval for steps
1-17 is complete. The worksheet enforces this: a **Draft** can be saved with any subset
of fields, but a `recommendation` cannot be recorded while any required field in steps
1-17 is still empty.

### Output standards

- Every analytical section ends with a **Confidence Assessment** (spec below).
- All quantitative claims cite data sources.
- All forward-looking statements include explicit assumptions.
- No recommendation without a corresponding risk decomposition (step 16 precedes 18).
- Work may be saved as a **Draft** at any time; only a **Final** save requires the full
  worksheet.

---

## Confidence Assessment (spec — defined once, used everywhere)

Each analytical section records a confidence level. When the level is **Low**, a written
note explaining why is mandatory (the worksheet enforces this). The full three-reason
block is mandatory in step 18:

```text
Confidence Level: [High / Medium / Low]
Reasons:
- Data quality: [assessment]
- Forecast uncertainty: [assessment]
- Sensitivity to assumptions: [assessment]
- Variant perception conviction: [assessment]   (step 18 only)
```

---

## Workflow Steps

Each step lists its field ids (`schema.py`) with type: `text`, `textarea`, `select`,
`score` (integer 1-10). **bold** = required to save. Selects always include the unset
placeholder, which fails validation if the field is required.

### 1. Investment universe — `universe`

Inputs: `reference.securities` (active flag, type, sector filters).

| Field id | Type | Notes |
|---|---|---|
| `universe_filters` | text, **required** | Sector, market-cap and geographic filters applied |
| `universe_rationale` | textarea | Why this is the right hunting ground |

### 2. Macro & credit — `macro`

Inputs: external macro & credit data (dashboard in step inputs panel); warehouse
regime features where available (`economic_credit_cycle_dividend_regime.md` framework).

| Field id | Type | Notes |
|---|---|---|
| `macro_backdrop` | textarea, **required** | Growth, inflation, rates, regime |
| `ig_spreads` | text | Investment grade spreads vs. historical average |
| `hy_spreads` | text | High yield spreads vs. historical average |
| `cds_trend` | select | Improving / Flat / Deteriorating |
| `default_rates` | text | Current vs. trend |
| `distressed_ratio` | text | Distressed debt ratio |
| `refinancing_wall` | text | Near-term maturities for the target sector |
| `credit_verdict` | select, **required** | Bullish / Neutral / Bearish |
| `credit_rationale` | textarea, **required** | 2-3 sentences |
| `confidence` | select | Section confidence (spec above) |
| `confidence_note` | textarea | Required only when `confidence` is Low |

**Relevance:** critical for banks, REITs, preferred securities, leveraged companies and
cyclicals.

### 3. Industry analysis — `industry`

| Field id | Type | Notes |
|---|---|---|
| `industry_outlook` | textarea, **required** | Growth drivers, structure, pricing power |
| `competitive_landscape` | textarea | Concentration, key competitors, positioning |
| `confidence` / `confidence_note` | | Section confidence |

### 4. Industry structure & capital cycle — `capital_cycle`

| Field id | Type | Notes |
|---|---|---|
| `capacity_growth` | text | X% YoY, trend |
| `competitor_capex` | select | Increasing / Decreasing / Stable |
| `supply_changes` | text | Additions and removals |
| `barriers` | select, **required** | High / Moderate / Low |
| `utilization` | text | Current vs. historical average |
| `profitability_trend` | select | Improving / Deteriorating / Stable |
| `capital_discipline_score` | score, **required** | 1-3 poor (overbuilding, destructive competition); 4-6 moderate; 7-10 strong (rational, returns-focused) |
| `confidence` / `confidence_note` | | Section confidence |

**Relevance:** essential for semiconductors, energy, mining, shipping, chemicals, REITs
and industrials — many opportunities are driven by supply constraints rather than
revenue growth.

### 5. Supply side — `supply`

| Field id | Type | Notes |
|---|---|---|
| `supply_analysis` | textarea, **required** | Capacity, entrants, constraints |
| `confidence` / `confidence_note` | | Section confidence |

### 6. Demand side — `demand`

| Field id | Type | Notes |
|---|---|---|
| `demand_analysis` | textarea, **required** | Volume/price drivers, customer structure |
| `confidence` / `confidence_note` | | Section confidence |

### 7. Consensus expectations — `consensus`

Inputs: external estimate data (revenue/EPS estimates, revision breadth).

| Field id | Type | Notes |
|---|---|---|
| `fy_revenue_est` | text | Current FY revenue estimate |
| `fy_eps_est` | text | Current FY EPS estimate |
| `next_fy_revenue_est` | text | Next FY revenue estimate |
| `next_fy_eps_est` | text | Next FY EPS estimate |
| `revision_trend` | select | Upward / Flat / Downward |
| `estimate_dispersion` | select | Low / Moderate / High |
| `surprise_implication` | textarea | What the setup implies for earnings surprises |

**Purpose:** makes expectation mismatches identifiable before thesis formation.

### 8. Variant perception — `variant` (highest priority)

| Field id | Type | Notes |
|---|---|---|
| `consensus_revenue_growth` | text | Consensus view |
| `consensus_eps_growth` | text | Consensus view |
| `consensus_margins` | select | Expanding / Flat / Compressing |
| `consensus_capital_allocation` | text | Buybacks / M&A / dividends / debt paydown |
| `consensus_multiple` | text | Current vs. historical |
| `my_revenue_growth` | text | Your view |
| `my_eps_growth` | text | Your view |
| `my_margins` | select | Expanding / Flat / Compressing |
| `my_capital_allocation` | text | Your view |
| `my_multiple` | text | Your view |
| `bullish_variant` | textarea, **required** | Why the market may be wrong (upside) |
| `bearish_variant` | textarea, **required** | Why the market may be wrong (downside) |
| `key_evidence` | textarea, **required** | One piece of evidence per line (min. 3) |
| `confidence` / `confidence_note` | | Section confidence |

**Purpose:** forces identification of informational, analytical and behavioural edge —
the source of excess returns. Validation requires at least three evidence lines.

### 9. Company deep-dive — `company`

Inputs: warehouse context panel (`model.features`, `model.scores`,
`fundamentals.periodic_financials`, `clean.company_profile`).

| Field id | Type | Notes |
|---|---|---|
| `business_model` | textarea, **required** | How the company makes money |
| `financial_analysis` | textarea, **required** | Growth, margins, balance sheet, cash flows |
| `confidence` / `confidence_note` | | Section confidence |

### 10. Earnings quality — `earnings_quality`

Inputs: `model.features` (cash conversion, margins) and `fundamentals.periodic_financials`.

| Field id | Type | Notes |
|---|---|---|
| `cash_conversion` | text | CFO / Net income, vs. historical |
| `accrual_ratio` | text | (Net income - CFO) / total assets |
| `sbc_pct` | text | Stock-based compensation as % of revenue |
| `gaap_gap` | text | GAAP vs. non-GAAP gap ($) |
| `working_capital` | text | Source or use of cash |
| `one_time_items` | textarea | Recurring vs. one-time adjustments, itemised |
| `quality_verdict` | select, **required** | High quality / Moderate / Low quality |
| `red_flags` | textarea | List, if any |
| `confidence` / `confidence_note` | | Section confidence |

**Purpose:** identifies low-quality earnings before they distort valuation.

### 11. Competitive advantage — `moat`

| Field id | Type | Notes |
|---|---|---|
| `network_effects` | select | Present / Absent |
| `scale_advantage` | select | Present / Absent |
| `brand_strength` | select | Present / Absent |
| `switching_costs` | select | High / Moderate / Low |
| `cost_leadership` | select | Present / Absent |
| `regulatory_advantage` | select | Present / Absent |
| `moat_rating` | select, **required** | Strong / Moderate / Weak / None |
| `durability_trend` | select | Improving / Stable / Eroding |
| `confidence` / `confidence_note` | | Section confidence |

**Purpose:** separates compounders from cyclical trades and value traps.

### 12. Management — `management`

Inputs: proxy/filing data, insider transactions (external).

| Field id | Type | Notes |
|---|---|---|
| `track_record` | textarea | Delivery vs. promises |
| `capital_allocation_history` | textarea | Value-accretive or destructive |
| `guidance_accuracy` | text | Beat/miss pattern |
| `insider_ownership` | text | % — meaningful or token |
| `insider_transactions` | select | Buying / Selling / Mixed / None |
| `compensation_alignment` | textarea | Tied to ROIC, EPS or opaque metrics |
| `management_score` | score, **required** | 1-10 |
| `confidence` / `confidence_note` | | Section confidence |

**Purpose:** execution risk and stewardship quality.

### 13. Valuation — `valuation`

| Field id | Type | Notes |
|---|---|---|
| `valuation_methods` | textarea, **required** | Methods used and the arithmetic |
| `key_assumptions` | textarea, **required** | Every forward-looking assumption |
| `target_price` | text | Per share, with currency |
| `margin_of_safety` | text | Vs. current price |
| `confidence` / `confidence_note` | | Section confidence |

### 14. Scenarios — `scenarios`

| Field id | Type | Notes |
|---|---|---|
| `base_case` | textarea, **required** | Narrative + expected 12M return |
| `bull_case` | textarea, **required** | Narrative + expected 12M return |
| `bear_case` | textarea, **required** | Narrative + expected 12M return |
| `scenario_probabilities` | text | e.g. 60 / 25 / 15 |
| `expected_return` | text | Probability-weighted forward 12M return |
| `confidence` / `confidence_note` | | Section confidence |

### 15. Historical analogs — `analog`

| Field id | Type | Notes |
|---|---|---|
| `similar_setups` | textarea, **required** | Markdown table: date, conditions, forward 12M return, outcome (3+ rows) |
| `base_rate` | text | % of similar conditions produced positive returns |
| `key_differences` | textarea | How today differs (numbered) |
| `analog_implication` | textarea | What the base rate implies here |
| `confidence` / `confidence_note` | | Section confidence |

**Purpose:** prevents narrative-driven conclusions; improves probabilistic thinking.

### 16. Risk decomposition — `risk`

| Field id | Type | Notes |
|---|---|---|
| `business_risk` | select, **required** | High / Moderate / Low |
| `valuation_risk` | select, **required** | High / Moderate / Low |
| `balance_sheet_risk` | select, **required** | High / Moderate / Low |
| `macro_risk` | select, **required** | High / Moderate / Low |
| `regulatory_risk` | select, **required** | High / Moderate / Low |
| `liquidity_risk` | select, **required** | High / Moderate / Low |
| `overall_risk_score` | score, **required** | 1-10 |
| `position_sizing` | textarea, **required** | Position-sizing implication |
| `confidence` / `confidence_note` | | Section confidence |

**Purpose:** differentiated position sizing by risk category rather than a generic
"risk is moderate".

### 17. Portfolio integration — `portfolio`

| Field id | Type | Notes |
|---|---|---|
| `factor_growth` | select | High / Moderate / Low |
| `factor_value` | select | High / Moderate / Low |
| `factor_quality` | select | High / Moderate / Low |
| `factor_momentum` | select | Positive / Neutral / Negative |
| `factor_low_volatility` | select | High / Moderate / Low |
| `factor_size` | select | Large / Mid / Small |
| `factor_rate_duration` | select | High / Moderate / Low |
| `factor_usd_exposure` | select | High / Moderate / Low |
| `existing_tilts` | textarea | Existing portfolio tilts |
| `position_adds` | textarea | What this position adds |
| `concentration_risk` | textarea | Concentration risk description |
| `correlation_assessment` | textarea | Correlation with existing holdings |

**Purpose:** avoids unintended factor concentration at the portfolio level.

### 18. Recommendation — `final`

| Field id | Type | Notes |
|---|---|---|
| `thesis` | text, **required** | 3 sentences maximum |
| `recommendation` | select, **required** | Buy / Add / Hold / Trim / Sell |
| `variant_summary` | textarea, **required** | Consensus vs. your view |
| `risk_summary` | textarea, **required** | Risk decomposition summary |
| `position_recommendation` | text, **required** | e.g. "2.5% of NAV" |
| `catalyst_timeline` | textarea, **required** | What changes the view, and when |
| `kill_switch` | textarea, **required** | What invalidates the thesis |
| `confidence_overall` | select, **required** | High / Medium / Low |
| `data_quality` | textarea, **required** | Confidence reason |
| `forecast_uncertainty` | textarea, **required** | Confidence reason |
| `sensitivity_assumptions` | textarea, **required** | Confidence reason |
| `variant_conviction` | textarea, **required** | Confidence reason |

---

## Structured Output Format

### JSON payload

`analysis.investment_analyses.payload` (JSONB) holds exactly:

```json
{
  "version": 1,
  "sections": {
    "<section_id>": {
      "<field_id>": "<value>",
      "confidence": "High",
      "confidence_note": ""
    }
  }
}
```

- `version` is `analysis_schema.SCHEMA_VERSION`; bump it on any breaking field change.
- Select values are stored as their display text; unset selects are stored as `""`.
- Scores are stored as integers 1-10.
- Empty text fields are stored as `""`.

### Validation rules (enforced on save)

Saving as **Draft** (`analysis_schema.validate_draft`) enforces the structural rules plus
the sequence gate:

1. The payload has a `sections` object and every section present.
2. Every select value is either `""` (unset) or one of its declared options.
3. Scores are integers in 1-10.
4. At least one field is filled (an entirely empty worksheet is refused).
5. No `recommendation` is recorded while steps 1-17 are incomplete.

Saving as **Final** (`analysis_schema.validate`) enforces everything above and:

6. Every **required** field is present and non-empty (after strip).
7. `confidence == "Low"` on a section requires a non-empty `confidence_note`.
8. `variant.key_evidence` has at least three non-empty lines.
9. `final.thesis` has at most three sentences (three `.`, `!` or `?` terminators).
10. `scenarios.scenario_probabilities`, once it contains digits, is exactly three
    numbers summing to 100.
11. `analog.base_rate`, once it contains digits, is a single percentage from 0 to 100.

The page shows per-step progress (`filled/total` required fields) on each section header
and opens the first incomplete section. Concurrent saves are refused with a message
rather than silently overwriting a newer version: each worksheet tracks its row's
`updated_at` and re-reads it before writing. A **Final** worksheet returns to **Draft**
only when the save explicitly reopens it. Every save is kept as an append-only revision
(`analysis.investment_analysis_revisions`, migration V0088); the sidebar's History panel
lists them, so the concurrency refusal is recoverable rather than a dead end.

### Markdown export

`analysis_schema.to_markdown(payload, ticker)` renders the document form: one `##`
heading per step in workflow order, `**Field label:** value` per non-empty field, and
the confidence block at the end of each analytical section. This is the format pasted
into an external LLM chat when a generated (LLM-assisted) report is wanted.

---

*This document mirrors `app/analysis_schema.py`; keep both in sync.*
