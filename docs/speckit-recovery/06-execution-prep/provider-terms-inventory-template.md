# Provider Terms Inventory Template (Draft)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation |
| Date | 2026-11-15 |
| Purpose | Capture provider licensing/terms evidence for `DEC-001` / `NFR-GOV-03` (no legal determination made) |
| Status | **Template; requires legal/product owner completion** |

## Instructions
- Complete one row per provider/source used for ingestion, enrichment, pricing, macro, fundamentals, filings, or derived analytics.
- Attach/source links to terms, API agreements, pricing plans, and redistribution policies as evidence artifacts.
- Mark unknown/unverified fields explicitly as `Unknown`; do not infer rights.
- Record review date, reviewer, and decision impact (allowed internal use, caching, redistribution, derived-data publication, retention).

## Inventory
| Provider | Data/services used | Account/plan/tier | Contract/terms URL or artifact | Internal research use | Caching/storage allowed | Redistribution/external sharing | Derived data/product use | Attribution/notice requirements | Retention/deletion constraints | Rate/access constraints | Review date | Reviewer/owner | Status | Notes / evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SEC EDGAR / data.sec.gov | Filings, submissions, company facts, XBRL (as applicable) | Public / N/A |  |  |  |  |  |  |  | Fair-access/user-agent policy applies (`SEC_USER_AGENT`) |  |  | Pending | Verify specific datasets/endpoints and redistribution terms |
| Yahoo Finance / yfinance (via OpenBB or direct) | Prices, dividends, splits/profiles (as applicable) |  |  |  |  |  |  |  |  |  |  |  | Pending | Confirm terms for automated access, storage, redistribution |
| FMP (Financial Modeling Prep) | Dividends/fundamentals/DCF/profiles/macro (as applicable) |  |  |  |  |  |  |  |  |  |  |  | Pending | Confirm plan-specific rights |
| Polygon.io | Dividend reconciliation/reference data (as applicable) |  |  |  |  |  |  |  |  |  |  |  | Pending | Confirm key/plan terms |
| OpenBB platform/providers | Provider routing/SDK access |  |  |  |  |  |  |  |  |  |  |  | Pending | Distinguish OpenBB SDK terms from upstream provider terms |
| FRED / ALFRED (macro) | Macro series/vintages |  |  |  |  |  |  |  |  |  |  |  | Pending | Confirm citation/redistribution rules |
| Other (specify) |  |  |  |  |  |  |  |  |  |  |  |  | Pending | Add any additional configured sources |

## Decision log
| Decision ID | Scope | Decision | Effective date | Approver | Linked requirements/risks | Follow-up actions |
|---|---|---|---|---|---|---|
| DEC-001 | Provider terms/licensing and redistribution posture | Pending |  |  | `NFR-GOV-03`, `DG-11`, `DC-04`, `RK-13`, `TSK-004` | Complete inventory; update constitution/gates/docs |
