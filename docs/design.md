# Energy Trading Lakehouse: Design Document

Implementation follows [backlog.md](backlog.md).
Repository: `sruthimn/energy-trading-lakehouse` (public, MIT licence)

---

## 0. Summary

A data platform for a fictional energy trading company, built on synthetic data and two public APIs. Data is ingested with **Azure Data Factory (ADF)**, stored in **ADLS Gen2** as Delta tables and transformed on **Azure Databricks** (Bronze, Silver) and **dbt** (Gold). Infrastructure is created with **Terraform** and every change is checked by **GitHub Actions**.

The reasons for choosing ADF ingestion on Azure over local Python ingestion are recorded in [ADR 0002](decisions/0002-azure-first-with-adf-ingestion.md). Local mode is used only for unit tests and the data generator.

## 1. Learning goals and where each one lives

| Topic | Where it lives | How it is demonstrated |
|---|---|---|
| Watermarking | Incremental load of `trades` | Control table, a failed run, a rerun with no loss or duplicates |
| Full load | `commodities` | Truncate and reload with a row-count check |
| Change data capture | Counterparty and book change logs | Inserts, updates and a delete flowing through, and the SCD2 history they create |
| REST API ingestion | FX rates and grid forecast | Date-window requests, then **pagination** (offset and limit, next link) with rate-limit handling |
| Schema validation | After Bronze | A schema change is detected and the batch is quarantined |
| Data profiling | Bronze data | Written findings on counts, nulls, ranges, versions and late rows |
| Infrastructure as code | Terraform | `plan` reviewed before every `apply` |
| CI/CD | GitHub Actions | Format, validate, plan and tests on every pull request |
| Databricks and dbt | Silver notebooks, Gold models | Tested models running on the shared workspace |

## 2. Scope

**In scope:** synthetic source system, four load patterns (full, watermark, CDC, REST API), Bronze, schema validation, data profiling, Silver, Gold (dbt) with SCD2, data quality and reconciliation, Terraform, CI, documentation.

**Next phase:** Airflow on AKS, automated deployment (needs a GitHub OIDC app registration), the Kafka real-time track, price data and schema-drift scenarios.

**Out of scope:** real company data, machine learning models, Synapse and Power BI.

**Disclosure.** The README states that the data is synthetic and that the project implements a pattern the author has used professionally. It quotes no production figures from any employer. The repository contains no subscription IDs, tenant IDs, workspace names or organisation-specific names.

## 3. Fictional business context

*Northgate Energy Trading* (fictional) trades GB power, NBP and TTF gas, Brent crude and UK carbon allowances across several desks. Problems the platform addresses:
1. The same trade shows different volumes in different reports, because units and amendments are handled inconsistently.
2. Daily batches are fragile and dashboards are stale at the start of the trading day.
3. A monthly regulatory submission is assembled and reconciled by hand.
4. Upstream systems change their schemas without notice.
5. Credit risk needs the counterparty rating **as at the trade date**, not today.

## 4. Load patterns (core of the project)

| Pattern | Source | Mechanism | Handles deletes? | Failure behaviour |
|---|---|---|---|---|
| **Full load** | `commodities` | Truncate, reload, compare row counts with the source | Yes (table replaced) | Row-count check blocks a truncated load |
| **Incremental (watermark)** | `trades` | Read rows where `last_modified` is after the saved watermark minus a 2-day lookback. Advance the watermark only after the load succeeds | **No** (a deleted row is invisible) | Watermark unchanged, so a rerun is safe |
| **CDC** | `cdc_counterparties`, `cdc_books` | Read the change log after the last `lsn`. Each row carries an operation: I, U or D | **Yes** | Last `lsn` unchanged, so a rerun is safe |
| **REST API** | FX rates, wind and solar forecast | ADF REST connector. FX rates: one request per date window. Forecast: pagination rules request page after page until the total is reached | Not applicable | Raw responses retained, row counts validated |

**Why watermark alone is not enough.** Late-arriving rows have a `last_modified` older than the watermark, so a plain watermark misses them (defect D03). The 2-day lookback catches them, at the cost of reading some rows twice. Bronze keeps the repeats and Silver removes them (see [ADR 0001](decisions/0001-bronze-append-with-lookback.md)). A watermark also cannot see deletes (defect D17), which is why reconciliation against control totals exists and why the master tables use CDC.

**REST API specifics.** The FX source (Frankfurter, ECB reference rates) needs no key and has no paging: one call returns a date range. Rates exist on working days only. The forecast source (NESO data portal, CKAN datastore) needs no key and pages with `limit` and `offset`; each response includes the `total` and a `next` link. Public APIs can be rate-limited, so page requests are spaced and retried with back-off.

## 5. Source system and synthetic data

### 5.1 The simulated source
A SQLite database (`etrm.db`) produced by the generator, then loaded into an **Azure SQL Database** (serverless) that acts as the ETRM source. Change data capture uses explicit change-log tables with an operation, a sequence number (`lsn`) and a commit time, so the behaviour is identical locally and in Azure.

### 5.2 Source inventory

| Source | Load pattern | Notes |
|---|---|---|
| `trades` | Watermark | `trade_id`, `trade_version`, `status` (CONFIRMED, PENDING, AMENDED, CANCELLED), `last_modified`, unit and price fields |
| `commodities` | Full load | Small reference table |
| `books`, `counterparties` | Reference tables, changed through CDC | Current state in the source |
| `cdc_counterparties`, `cdc_books` | CDC | Operation, `lsn`, commit time |
| FX rates API | REST, date window | Public, no key |
| Wind and solar forecast API | REST, paginated | Public, no key. Half-hourly settlement periods |
| `control_totals/date=YYYY-MM-DD/control_totals.csv` | File, used for reconciliation | Row counts per day |

Tables not read by pipelines: `sim_state`, `sim_truth`, `sim_deleted_trades` and `_truth/defects.json` belong to the generator and are the answer sheet for tests.

### 5.3 Data delivery
1. The generator is written and tested in this repository and is seeded, so output is identical every time.
2. A GitHub Actions workflow (`simulate-source-day`) advances the Azure SQL source by one business day, on demand or on a schedule.
3. Only a small sample dataset is ever committed. Generated data is never committed.

Default volume is about **20,000 trades per business day** (smaller while developing).

### 5.4 Defect catalogue
The generator records a truth manifest of exact counts, and tests compare the pipeline output with it.

| ID | Defect | Handled by | Status |
|---|---|---|---|
| D01 | Trade amendments (versions 1 to N) | Silver keeps the latest valid version | Implemented |
| D02 | Cancellations | Status handling | Implemented |
| D03 | Late-arriving rows (about 0.5%) | Watermark lookback, Silver deduplication | Implemented |
| D04 | Null mandatory fields | Quarantine | Implemented |
| D05 | Delivery end before start, bad ranges | Quarantine | Implemented |
| D06 | Mixed units | Unit normalisation | Implemented |
| D07 | Clock-change days (46 and 50 periods) | Settlement calendar | Implemented |
| D08 | Counterparty downgrade | SCD2 and as-at-trade-date join | Implemented |
| D09 | Duplicate stream events | Idempotent by `event_id` | Planned (next phase) |
| D10 | Additive schema drift | Schema validation records and continues | Planned |
| D11 | Breaking schema drift | Schema validation quarantines the batch | Planned |
| D12 | Missing FX rate | Flagged fallback | Planned |
| D13 | Price outliers | Quality check flags | Planned |
| D14 | Orphan counterparty reference | Quarantine with reason | Implemented |
| D15 | Stale file re-delivered | Freshness check | Planned |
| D16 | Counterparty deleted at source | CDC applies the delete, history preserved | Implemented |
| D17 | Hard-deleted trade rows | Reconciliation to control totals catches it | Implemented |

Full-size demonstration (seed 42, 20,000 trades a day, 18 days): 209 empty fields (D04), 87 bad ranges (D05), 76 orphan counterparties (D14), 5 deleted trades (D17), 296 rejected rows.

### 5.5 Simulated timeline
Default start 2026-03-16. 19 March: book BK-UKGAS-03 moves to desk EUGAS. 24 March: a counterparty is downgraded. 26 March: a counterparty is onboarded. 29 March: clock change (46 half-hours). 2 April: five old trades are hard deleted. 6 April: a counterparty is deleted while 946 trades still reference it. The autumn clock change (50 periods) is a separate fixture.

## 6. Architecture

```
GitHub Actions: simulate-source-day
        | advances the source by one business day
        v
SOURCES                         ADF                              ADLS GEN2 + DATABRICKS (shared workspace)
Azure SQL (etrm)  ----------->  pl_incremental_trades  --+
  trades, commodities,          pl_full_reference         |       LANDING  (files as copied)
  cdc_counterparties,           pl_cdc_counterparties_    +--->     |
  cdc_books                       books                   |       BRONZE   append-only Delta, audit columns
FX rates API (REST)  -------->  pl_api_fx_rates           |         |  schema validation, reconciliation, profiling
Forecast API (REST, paged) -->  pl_api_forecast  ---------+       SILVER   latest version, quality rules, SCD2,
                                                                    |        quarantine
control table ctl.watermark (Azure SQL): watermark and lsn per source GOLD     dbt models and tests
Secrets: Key Vault          CI: GitHub Actions (fmt, validate, plan, tests)
Next phase: Airflow on AKS, automated deployment, Kafka real-time
```

### 6.1 Azure resources (Terraform)
Resource group (read, not created), ADLS Gen2 account with containers `landing`, `bronze`, `silver`, `gold` and `quarantine`, Key Vault (access policies, generated SQL password), Azure SQL server and serverless database `etrm` (`GP_S_Gen5_2`, the serverless size allowed by policy, 0.5 vCore minimum, auto-pause after 60 minutes), and Data Factory with linked services to Key Vault, Azure SQL and the lake. Names carry a random suffix. 19 resources in total.

Databricks is **not** created by Terraform: the project uses an existing shared workspace, working only in its own folder and schema and changing no workspace settings. The workspace sits in a different Azure region from the lake, so a small cross-region data cost is accepted.

### 6.2 Local versus Azure

| Concern | Local mode | Azure |
|---|---|---|
| Purpose | Unit tests and the generator | The real demonstration |
| Source | SQLite | Azure SQL |
| Ingestion | Not used | ADF |
| Compute and Delta | PySpark and Delta Lake | Azure Databricks |
| Gold | Not used | dbt on Databricks (`dbt-databricks`) |
| Secrets | `.env` (ignored by git) | Key Vault |

Business logic that can be unit-tested (for example version selection and unit conversion) is written as plain functions so it runs in both places.

## 7. Layer design

### 7.1 Ingestion (ADF)
A control table `ctl.watermark` in Azure SQL holds, per source: load type, watermark or last `lsn`, last status and rows loaded.

| Pipeline | Steps |
|---|---|
| `pl_incremental_trades` | LookupOldWatermark, LookupNewWatermark, CopyIncremental (rows after watermark minus 2 days), UpdateWatermark (stored procedure, runs only after a successful copy) |
| `pl_full_reference` | Copy, truncate and reload, compare row counts |
| `pl_cdc_counterparties_books` | Read changes after the last `lsn`, land I, U and D rows in order, save the new `lsn` after landing |
| `pl_api_fx_rates` | REST linked service, one request per date window, land raw JSON, validate row count |
| `pl_api_forecast` | REST pagination rules (offset and limit, follow the `next` link until the total is reached), spaced requests, land every page as raw JSON |

Secrets are read from Key Vault through linked services, and ADF uses a managed identity.

### 7.2 Bronze
Exact append-only copy plus audit columns (`_ingested_at`, `_source_system`, `_batch_run_id`, `_source_file`, and for CDC `_operation` and `_lsn`). No casting, renaming or filtering. Repeated rows from the lookback are expected: compare **distinct keys** with the source, not raw counts.

### 7.3 Schema validation
After each Bronze load, compare the incoming schema with the expected schema: columns, types and nullability. Missing or unknown columns are flagged. A failing batch is moved to quarantine and the result (pass or fail, with reasons) is recorded per batch. Silver always selects columns explicitly, never `SELECT *`.

### 7.4 Data profiling
A time-boxed exploration of the Bronze data: row counts, null rates, value ranges, trade versions, late-arriving rows and distribution of statuses. Findings are written to `docs/data-profile.md` and drive the Silver rules.

### 7.5 Silver
1. Separate valid and invalid rows. Invalid rows go to quarantine with a reason and timestamp.
2. Apply CDC changes (inserts, updates, deletes) and build SCD2 history for counterparties and books.
3. Keep the highest valid `trade_version` per trade.
4. Normalise units, convert to UTC, expand to half-hourly settlement periods.
5. Idempotent writes. Fail if the reject rate exceeds a threshold.

### 7.6 Gold (dbt on Databricks)
Staging, intermediate and marts. Tests: unique, not_null, relationships, accepted_values, ranges, no overlapping SCD2 ranges, and reconciliation to control totals. A failing test blocks publication.

### 7.7 Data model

| Table | Type | Grain |
|---|---|---|
| `fact_trade` | Transaction fact | One row per trade (latest valid version) |
| `fact_daily_position` | Periodic snapshot | Book x commodity x delivery period x business date |
| `dim_counterparty` | SCD2 (fed by CDC) | Counterparty x effective range |
| `dim_book` | SCD2 (fed by CDC) | Book x effective range |
| `dim_commodity`, `dim_delivery_period`, `dim_date` | Type 1 / generated | |

### 7.8 Data quality
Layered checks: row counts at landing, schema validation after Bronze, quality rules in Silver, dbt tests in Gold, and daily reconciliation to control totals. Rejected rows are retained with the reason attached.

### 7.9 Orchestration
ADF triggers run the pipelines on a schedule. In the next phase an Airflow DAG on AKS orders ADF, Databricks and dbt with retries and alerts.

## 8. CI/CD and infrastructure as code

### 8.1 Continuous integration (every pull request)
Lint, unit tests, generator tests against the truth manifest, `terraform fmt` and `validate`, a `terraform plan`, dbt parse and tests, and a secret scan.

### 8.2 Continuous delivery (next phase)
Authenticate to Azure with GitHub OIDC (needs an app registration), `terraform apply` from a protected workflow with an approval gate, then deploy notebooks and dbt.

### 8.3 Cost controls
Serverless SQL with auto-pause, small data volumes, no resources that are not needed, and a plan reviewed before every apply.

## 9. Acceptance criteria

1. Every implemented defect matches the truth manifest exactly.
2. Rerunning any day gives identical results for all four load patterns.
3. A failed incremental load leaves the watermark unchanged, and a rerun loads everything once.
4. A CDC delete closes the dimension record without losing history.
5. The watermark blind spot (D17) is demonstrated and caught by reconciliation.
6. The paginated API pipeline loads every page of the forecast and its row count matches the reported total.
7. A schema change in a source batch is detected after Bronze and the batch is quarantined.
8. Gold reconciles to control totals, and a deliberately broken run is blocked.
9. CI passes on a pull request, and `terraform plan` is reviewed before `apply`.
10. A new reader understands the system from the README in ten minutes.

## 10. Repository structure

```
README.md  LICENSE  CONTRIBUTING.md  Makefile  pyproject.toml
docs/            design, backlog, data notes, data profile, ADRs
src/lakehouse/   generator/ (done), validation/, silver/ (shared logic and tests)
infra/terraform/ foundation (19 resources)
adf/             pipeline and linked service definitions (exported JSON)
databricks/      Bronze, validation and Silver notebooks
dbt/             Gold models, macros, tests
tests/           unit tests
.github/         workflows, issue and pull request templates
```

## 11. Engineering standards
`main` is protected. All changes go through pull requests with checks required. Small commits, imperative messages, short ADRs for decisions, tests before core logic. Commits are authored by the repository owner.

## 12. Verified, unverified and open items

| Item | Status |
|---|---|
| Generator and its tests (PySpark 3.5.3, Delta 3.2.1, 105 tests) | **Verified** |
| Terraform foundation syntax | **Validated only**. Not yet planned or applied |
| Frankfurter FX API and NESO forecast API reachable without a key | **Verified** with a test call. Rate limits **not verified** |
| Shared Databricks workspace can read and write the lake | **Open** |
| dbt can run against the shared workspace (SQL warehouse or cluster) | **Open** |
| Permission to register Azure resource providers | **Open** |
| GitHub OIDC to Azure | **Open** (needs an app registration). Next phase |

## 13. Delivery order
1. Azure foundation: Terraform plan and apply, source loaded into Azure SQL
2. ADF ingestion: control table, full load, FX API, incremental trades
3. CDC, paginated forecast API, Bronze, schema validation, reconciliation, profiling
4. Silver, quarantine, SCD2
5. Gold with dbt, CI on pull requests
6. End-to-end run and documentation
7. Next phase: Airflow on AKS, automated deployment, Kafka real-time, price data, schema drift
