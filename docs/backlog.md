# Backlog

Epics 0 and 1 keep the numbers of their GitHub issues (#1 to #19). Epics 2 onwards are not yet issues. Each item becomes an issue when it is scheduled.

Size: S (under half a day), M (about a day), L (2 to 3 days). Status: Done, Planned (current phase) or Next phase. Items marked [Azure] need the Azure subscription.

## Epic 0: Foundations
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 0.1 | Repository setup | LICENSE (MIT), README, .gitignore, CONTRIBUTING, PR and issue templates | S | Done |
| 0.2 | Branch protection | `main` protected, pull request required | S | Done |
| 0.5 | Project tooling | pyproject, Makefile (`setup`, `test`), pre-commit | S | Done |
| 0.7 | Dev container (optional way to run tests) | Open the repository, run tests with no manual installs | S | Done |

Spikes 0.3 (dbt on DuckDB), 0.4 (Great Expectations on Spark) and 0.6 (native Azure SQL CDC) are **withdrawn**: dbt runs on Databricks only, data quality uses validation rules and dbt tests, and CDC uses change-log tables.

## Epic 1: Synthetic source system and generator
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 1.1 | Reference data | Books, counterparties, commodities (fictional), seeded | S | Done |
| 1.2 | Trades with amendments and cancellations | D01, D02 | M | Done |
| 1.4 | Day-by-day simulation of the source database | One business day at a time, late rows (D03) | M | Done |
| 1.5 | Change log for master tables | Operation, `lsn`, commit time. D08, D16 | M | Done |
| 1.6 | Defect injection, truth manifest, control totals | D04 to D07, D14, D17 | M | Done |
| 1.9 | Generator tests and sample dataset | Determinism and manifest tests pass, small sample dataset committed | M | Planned |
| 1.3 | Price file | D13, D15. FX rates are now read from a public API | M | Next phase |
| 1.7 | Schema drift injection | D10, D11 | S | Next phase |
| 1.8 | Event stream generator | D09 | M | Next phase |
| 1.10 | Data contracts (YAML) | One per source, validated by a test | S | Next phase |

## Epic 2: Azure foundation **[Azure]**
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 2.1 | Terraform foundation merged | ADLS Gen2 (five containers), Key Vault, serverless Azure SQL, Data Factory with linked services: 19 resources | S | Planned |
| 2.2 | Plan and apply | Provider registrations checked, plan reviewed (19 to add, 0 to change, 0 to destroy), apply succeeds | M | Planned |
| 2.3 | Load the source into Azure SQL | The `etrm` database holds the simulated data | M | Planned |
| 2.4 | `simulate-source-day` workflow | Advances the Azure SQL source by one day on demand | M | Planned |
| 2.5 | Connect the shared Databricks workspace to the lake | A notebook reads and writes the lake | M | Planned |

## Epic 3: ADF ingestion **[Azure]**
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 3.1 | Control table and watermark procedure | `ctl.watermark`, update stored procedure | S | Planned |
| 3.2 | Full load: `pl_full_reference` | Truncated source blocked by the row-count check | S | Planned |
| 3.3 | FX rates API: `pl_api_fx_rates` | One request per date window, raw JSON landed, row count validated | M | Planned |
| 3.4 | Incremental trades: `pl_incremental_trades` | 2-day lookback, D03 handled, failed run leaves the watermark unchanged | M | Planned |
| 3.5 | CDC: `pl_cdc_counterparties_books` | Inserts, updates, deletes in order, resumes from the last `lsn` | L | Planned |
| 3.6 | Paginated API: `pl_api_forecast` | Every page loaded, row count equals the reported total, requests spaced for rate limits | M | Planned |
| 3.7 | Documentation: which load pattern when | `docs/load-patterns.md` with worked examples | S | Planned |

## Epic 4: Bronze, validation and profiling
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 4.1 | Bronze notebook | Append-only Delta with audit columns, CDC columns included | M | Planned |
| 4.2 | Schema validation | Expected columns, types and nullability. Failing batches quarantined, result recorded per batch | M | Planned |
| 4.3 | Reconciliation | Loaded distinct keys compared with control totals | S | Planned |
| 4.4 | Data profiling | `docs/data-profile.md` with counts, nulls, ranges, versions, late rows | S | Planned |

## Epic 5: Silver
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 5.1 | Valid and invalid split with quarantine | D04, D05, D14 equal truth | M | Planned |
| 5.2 | Latest version selection | D01 equals truth | S | Planned |
| 5.3 | CDC apply and SCD2 history | D08, D16 handled | L | Planned |
| 5.4 | Unit normalisation | D06 equals truth | M | Planned |
| 5.5 | Settlement calendar and time zones | D07 equals truth | L | Planned |
| 5.6 | Idempotent writes and reject threshold | Rerun test passes | M | Planned |

## Epic 6: Gold (dbt on Databricks)
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 6.1 | dbt project against the shared workspace | `dbt debug` and a first model run | M | Planned |
| 6.2 | SCD2 dimensions | No overlapping ranges | M | Planned |
| 6.3 | `fact_trade` with as-at-trade-date join | Old trades keep old ratings | M | Planned |
| 6.4 | `fact_daily_position` | Net volume by book, commodity and period | M | Planned |
| 6.5 | dbt tests and reconciliation | D17 caught, broken run blocked | M | Planned |

## Epic 7: Continuous integration
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 7.1 | CI workflow | Lint and unit tests on every pull request | M | Planned |
| 7.2 | Terraform checks | `fmt`, `validate` and `plan` on pull requests | M | Planned |
| 7.3 | dbt checks and secret scan | Fails on error or a planted test secret | S | Planned |

## Epic 8: Documentation and demonstration
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 8.1 | End-to-end run | Several simulated days, including a late row, a hard delete, an amended trade and an orphan counterparty | L | Planned |
| 8.2 | README, design and diagrams | A new reader understands the system in ten minutes | M | Planned |

## Epic 9: Next phase
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 9.1 | GitHub OIDC to Azure | No stored Azure passwords | M | Next phase |
| 9.2 | Automated deployment | Approval gate before `apply` | M | Next phase |
| 9.3 | Airflow on AKS | Daily DAG with retries, DAGs sync from Git | L | Next phase |
| 9.4 | Real-time track | File source, then Kafka. D09 handled | L | Next phase |
| 9.5 | Governance demo | Masking and desk filter | M | Next phase |
| 9.6 | Merge-based Bronze | Revisit append-only if volume grows (see ADR 0001) | M | Next phase |

## Suggested order
Epic 2, then 3, then 4, then 5 and 6, then 7 and 8. Epic 9 follows once the batch path works end to end.
