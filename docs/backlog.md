# Backlog

Epics 0 and 1 keep the numbers of their GitHub issues (#1 to #19). Epics 2 onwards are not yet issues. Each item becomes an issue when it is scheduled.

Size: S (under half a day), M (about a day), L (2 to 3 days). Status: Done, In progress, Planned (current phase) or Next phase. Items marked [Azure] need the Azure subscription and [DBX] need the shared Databricks workspace.

## Epic 0: Foundations
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 0.1 | Repository setup | LICENSE (MIT), README, .gitignore, CONTRIBUTING, PR and issue templates | S | Done |
| 0.2 | Branch protection | `main` protected, pull request required | S | Done |
| 0.5 | Project tooling | pyproject, Makefile (`setup`, `test`), pre-commit | S | Done |
| 0.7 | Dev container (optional way to run tests) | Open the repository, run tests with no manual installs | S | Done |

Spikes 0.3 (dbt on DuckDB), 0.4 (Great Expectations on Spark) and 0.6 (native Azure SQL CDC) are **withdrawn**: data quality uses declarative pipeline expectations and validation rules, and CDC uses change-log tables.

## Epic 1: Synthetic source system and generator
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 1.1 | Reference data | Books, counterparties, commodities (fictional), seeded | S | Done |
| 1.2 | Trades with amendments and cancellations | D01, D02 | M | Done |
| 1.4 | Day-by-day simulation of the source database | One business day at a time, late rows (D03) | M | Done |
| 1.5 | Change log for master tables | Operation, `lsn`, commit time. D08, D16 | M | Done |
| 1.6 | Defect injection, truth manifest, control totals | D04 to D07, D14, D17 | M | Done |
| 1.9 | Generator tests and sample dataset | Determinism and manifest tests pass, small sample dataset committed | M | Planned |
| 1.11 | Load the source into Azure SQL | `load` command, safe to rerun, tests | M | Done |
| 1.12 | File export (CSV and JSON) | `export` command writes a daily trade file (CSV) and counterparty change file (JSON Lines). Deterministic, written once, late rows in the file of the day they arrive, covered by tests. Copying the files to the lake is item 3.9 | M | Done |
| 1.3 | Price file | D13, D15. FX rates are read from a public API | M | Next phase |
| 1.7 | Schema drift injection | D10, D11 | S | Next phase |
| 1.8 | Event stream generator | D09 | M | Next phase |
| 1.10 | Data contracts (YAML) | One per source, validated by a test | S | Next phase |

## Epic 2: Azure foundation and environments **[Azure]**
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 2.1 | Terraform foundation | ADLS Gen2 (five containers), Key Vault, Data Factory with linked services. First version applied | S | Done |
| 2.2 | Use the shared SQL server | The project's own SQL server is removed. Linked service reads the shared server from variables. Applied: only the old SQL resources were destroyed | S | Done |
| 2.3 | Dev and prod environments | An `environment` variable, a variable file and a state per environment, names include the environment | M | Planned |
| 2.4 | Dev and prod databases | `etrm_dev` exists on the shared server (created by hand, Basic tier, because the organisation policy allows only Basic, S0 to S2 and `GP_S_Gen5_2`). `etrm_prod`, creation in Terraform and a project login each are still to do | M | In progress |
| 2.5 | Remote Terraform state | State in a storage account, one key per environment, local state migrated | S | Planned |
| 2.6 | Load the source into each database | The loader filled `etrm_dev` and the row counts match the source. A rerun check and `etrm_prod` are still to do | S | In progress |
| 2.7 | `simulate-source-day` pipeline | Advances the source by one day on demand | M | Planned |

## Epic 3: ADF ingestion, metadata-driven **[Azure]**
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 3.1 | Control table, procedures and seed rows | `ctl.watermark`, update and failure procedures, one row per source. Scripts in `adf/sql` ran in `etrm_dev` and the test script passed (the misspelled source name fails as intended) | S | Done |
| 3.2 | Metadata columns | Source path, format, target, enabled flag and parameters added to the control table | S | Planned |
| 3.3 | Generic pipeline `pl_ingest_generic` | ForEach over enabled rows, branch by load type, parameters for source and environment | M | Planned |
| 3.4 | Full load branch | Truncated source blocked by the row-count check | S | Planned |
| 3.5 | FX rates API branch | One request per date window, raw JSON landed, row count validated | M | Planned |
| 3.6 | Incremental trades branch | 2-day lookback, D03 handled, failed run leaves the watermark unchanged | M | Planned |
| 3.7 | CDC branch | Inserts, updates, deletes in order, resumes from the last `lsn` | L | Planned |
| 3.8 | Paginated API branch | Every page loaded, row count equals the reported total, requests spaced for rate limits | M | Planned |
| 3.9 | File branch | CSV and JSON files reach the landing zone | S | Planned |
| 3.10 | ADF in Git | Factory linked to the repository, definitions exported to `adf/` | S | Planned |
| 3.11 | Documentation: which load pattern when | `docs/load-patterns.md` with worked examples | S | Planned |

## Epic 4: Databricks access, Bronze and validation **[DBX]**
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 4.1 | Connect the workspace to the lake | A notebook reads and writes the landing zone. Unity Catalog schemas for dev and prod | M | Planned |
| 4.2 | Auto Loader into Bronze | Append-only Delta with audit columns. Each file read once | M | Planned |
| 4.3 | `dbutils` usage | Widgets for parameters, secrets from Key Vault, file checks, task values | S | Planned |
| 4.4 | Schema validation | Expected columns, types and nullability. Failing batches quarantined, result recorded per batch | M | Planned |
| 4.5 | Reconciliation | Loaded distinct keys compared with control totals | S | Planned |
| 4.6 | Data profiling | `docs/data-profile.md` with counts, nulls, ranges, versions, late rows | S | Planned |
| 4.7 | Join files in the lake | A Silver step joins two file sources without registered tables | S | Planned |

## Epic 5: Silver (declarative pipeline) **[DBX]**
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 5.1 | Valid and invalid split with quarantine | D04, D05, D14 equal truth | M | Planned |
| 5.2 | Latest version selection | D01 equals truth | S | Planned |
| 5.3 | CDC apply and SCD2 history (Auto CDC) | D08, D16 handled | L | Planned |
| 5.4 | Unit normalisation | D06 equals truth | M | Planned |
| 5.5 | Settlement calendar and time zones | D07 equals truth | L | Planned |
| 5.6 | Rerun safety and reject threshold | Rerun test passes | M | Planned |

## Epic 6: Gold **[DBX]**
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 6.1 | SCD2 dimensions | No overlapping ranges | M | Planned |
| 6.2 | `fact_trade` with as-at-trade-date join | Old trades keep old ratings | M | Planned |
| 6.3 | `fact_daily_position` | Net volume by book, commodity and period | M | Planned |
| 6.4 | Expectations and reconciliation | D17 caught, broken run blocked | M | Planned |

## Epic 7: Workflows and Asset Bundles **[DBX]**
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 7.1 | Lakeflow Job | Tasks in order, retries, task values, failure alert, serverless or job cluster | M | Planned |
| 7.2 | File-arrival trigger | A file in the landing zone starts the job | S | Planned |
| 7.3 | ADF starts the job | ADF calls the job after ingestion and passes parameters | S | Planned |
| 7.4 | Asset Bundle | `databricks.yml`, job and pipeline resources, wheel built from `src`, validates | M | Planned |
| 7.5 | Dev and prod targets | Same bundle deploys to both with different variables | S | Planned |

## Epic 8: Azure DevOps CI/CD
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 8.1 | Organisation, project and service connection | Pipeline can authenticate to Azure and the repository. The organisation and project exist and a pipeline built from GitHub runs. The service connection to Azure is still to do | M | In progress |
| 8.2 | CI pipeline | Lint, unit tests, `terraform fmt` and `validate`, `bundle validate`, secret scan on every pull request | M | Planned |
| 8.3 | Terraform plan in CI | Plan for dev shown on the pull request | M | Planned |
| 8.4 | Deploy pipeline | Dev stage applies the saved plan, runs SQL scripts, deploys ADF and the bundle | L | Planned |
| 8.5 | Prod stage with approval | Manual approval on the Azure DevOps Environment, then the same steps | M | Planned |
| 8.7 | Checks in both tools | `.github/workflows/ci.yml` and `pipelines/ci.yml` run lint, tests, Terraform format and validate, and a guard against tracked state files. Both pass. GitHub Actions runs on every pull request and the Azure pipeline is started by hand | S | Done |
| 8.6 | Retire the GitHub Actions checks | One CI tool once the Azure pipeline is proven, README updated | S | Planned |

## Epic 9: Security and governance **[DBX]**
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 9.1 | Access per layer | Grants: engineers on Bronze and Silver, analysts on Gold only | S | Planned |
| 9.2 | Row filter and column mask | A restricted user sees only their desk and a masked limit | M | Planned |
| 9.3 | Project logins on the shared SQL server | Each environment uses its own login, not the shared admin | S | Planned |

## Epic 10: Documentation and demonstration
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 10.1 | End-to-end run | Several simulated days, including a late row, a hard delete, an amended trade and an orphan counterparty | L | Planned |
| 10.2 | Incident write-up | The late-row problem: cause, detection, fix and what changed | S | Planned |
| 10.3 | Performance and cost notes | What to check for a slow job or MERGE, how compute is chosen, how cost is controlled | S | Planned |
| 10.4 | README, design and diagrams | A new reader understands the system in ten minutes | M | Planned |

## Epic 11: Next phase
| # | Issue | Acceptance criteria | Size | Status |
|---|---|---|---|---|
| 11.1 | Lakeflow Connect for SQL Server | Change tracking on the source, gateway, managed ingestion into Bronze | L | Next phase |
| 11.2 | dbt as a job task | Gold models tested with dbt, run from the job | M | Next phase |
| 11.3 | Airflow on AKS | Daily DAG with retries, DAGs sync from Git | L | Next phase |
| 11.4 | Real-time track | File source, then Kafka. D09 handled | L | Next phase |
| 11.5 | Merge-based Bronze | Revisit append-only if volume grows (see ADR 0001) | M | Next phase |

## Suggested order
Epic 2, then 3, then 4, then 5 and 6, then 7, then 8 and 9, then 10. Epic 11 follows once the batch path works end to end.
