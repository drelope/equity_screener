# ETL lessons ledger

One file per lesson. A lesson is `guarded` only if a named guard (a script, test or check) exists
in the repository; `python -m scripts.lessons_audit` enforces that. See
[the architecture](../etl-learning-architecture.md) for how lessons are captured and recalled.

| Lesson | Status | Area |
|---|---|---|
| [L001](L001-partial-title-list.md) | guarded | stage 1 |
| [L002](L002-mocked-sql-hides-driver-errors.md) | guarded | stage writers |
| [L003](L003-order-dependent-retype.md) | guarded | classification repair |
| [L004](L004-rekey-needs-title-evidence.md) | guarded | successor re-key |
| [L005](L005-duplicate-identities-hold-history.md) | guarded | reference.securities twins |
| [L006](L006-edits-silently-not-applied.md) | monitored | change process |
| [L007](L007-line-endings-flip.md) | open | repository hygiene |
| [L008](L008-title-classifier-faults.md) | open | title classifier |
| [L009](L009-universe-changes-need-a-backtest.md) | monitored | classification and selection |
| [L010](L010-adjusted-volume-is-not-share-volume.md) | monitored | price and liquidity rules |
