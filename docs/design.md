# Energy Trading Lakehouse: Design Document

Implementation follows [backlog.md](backlog.md).
Repository: `sruthimn/energy-trading-lakehouse` (public, MIT licence)

---

## 0. Summary

A data platform for a fictional energy trading company, built on synthetic data and two public APIs. Data is ingested with **Azure Data Factory (ADF)** from a shared Azure SQL server, two REST APIs and files, and lands in **ADLS Gen2**. **Azure Databricks** does the rest: Auto Loader and Lakeflow Spark Declarative Pipelines build Bronze, Silver and Gold as Delta tables, a Lakeflow Job runs the steps in order, and a Databricks Asset Bundle deploys the code. **Terraform** creates the Azure resources and **Azure DevOps Pipelines** deploy every change to a dev and a prod environment.

The reasons for the main choices are recorded in the [decision records](decisions). Local mode is used only for unit tests and the data generator.

## 1. Learning goals and where each one lives

| Topic | Where it lives | How it is demonstrated |
|---|---|---|
| Metadata-driven ingestion | Control table and one generic ADF pipeline | A new source is added with a row in the table, not a new pipeline |
| Parameterised pipelines | ADF pipeline parameters, Databricks widgets | The same pipeline runs for every source and environment |
| Watermarking | Incremental load of `trades` | Control table, a failed run, a rerun with no loss or duplicates |
| Full load | `commodities` | Truncate and reload with a row-count check |
| Change data capture | Counterparty and book change logs | Inserts, updates and a delete flowing through, and the SCD2 history they create |
| REST API ingestion | FX rates and grid forecast | Date-window requests, then **pagination** (offset and limit, next link) with rate-limit handling |
| File ingestion | CSV and JSON files in the landing zone | Auto Loader picks up each file as it arrives |
| Schema validation | After Bronze | A schema change is detected and the batch is quarantined |
| Data profiling | Bronze data | Written findings on counts, nulls, ranges, versions and late rows |
| Declarative pipelines | Lakeflow Spark Declarative Pipelines (formerly Delta Live Tables) | Expectations on every layer, SCD2 with Auto CDC |
| Databricks utilities | `dbutils` in notebooks | Widgets for parameters, secrets from Key Vault, file checks, task values |
| Workflows | Lakeflow Job | Tasks with retries, a file-arrival trigger and failure alerts |
| Packaging and deployment | Databricks Asset Bundle | Dev and prod targets, a Python wheel built and deployed with the job |
| Environments | Dev and prod | Separate databases, storage and schemas, deployed through an approval gate |
| Infrastructure as code | Terraform | `plan` reviewed before every `apply`, remote state |
| CI/CD | Azure DevOps Pipelines | Checks on every pull request, staged deployment |
| Governance | Unity Catalog | Access per layer, a row filter and a column mask |

## 2. Scope

**In scope:** synthetic source system, four load patterns (full, watermark, CDC, REST API) plus file ingestion, Bronze, schema validation, data profiling, Silver, Gold with SCD2, data quality and reconciliation, Databricks Workflows, Asset Bundles, Terraform, Azure DevOps, dev and prod environments, row and column security, documentation.

**Next phase:** Lakeflow Connect (managed SQL Server ingestion, which needs change tracking on the source and a gateway), dbt as an optional job task, Airflow on AKS, the Kafka real-time track, price data and schema-drift scenarios.

**Out of scope:** real company data, machine learning models, XML sources, Synapse and Power BI.

**Disclosure.** The README states that the data is synthetic and that the project implements a pattern the author has used professionally. It quotes no production figures from any employer. The repository contains no subscription IDs, tenant IDs, workspace names, server names or organisation-specific names.

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
| **Files** | CSV and JSON files | Written to the landing zone. Auto Loader reads each new file once | Not applicable | A file that fails validation is quarantined, the rest continue |

**Why watermark alone is not enough.** Late-arriving rows have a `last_modified` older than the watermark, so a plain watermark misses them (defect D03). The 2-day lookback catches them, at the cost of reading some rows twice. Bronze keeps the repeats and Silver removes them (see [ADR 0001](decisions/0001-bronze-append-with-lookback.md)). A watermark also cannot see deletes (defect D17), which is why reconciliation against control totals exists and why the master tables use CDC.

**REST API specifics.** The FX source (Frankfurter, ECB reference rates) needs no key and has no paging: one call returns a date range. Rates exist on working days only. The forecast source (NESO data portal, CKAN datastore) needs no key and pages with `limit` and `offset`; each response includes the `total` and a `next` link. Public APIs can be rate-limited, so page requests are spaced and retried with back-off.

## 5. Source system and synthetic data

### 5.1 The simulated source
A SQLite database (`etrm.db`) produced by the generator, then loaded into a database on a **shared Azure SQL server** that acts as the ETRM source. There is one database per environment (dev and prod), created by the project. The shared server itself is not managed by this repository. Change data capture uses explicit change-log tables with an operation, a sequence number (`lsn`) and a commit time, so the behaviour is identical locally and in Azure.

### 5.2 Source inventory

| Source | Load pattern | Notes |
|---|---|---|
| `trades` | Watermark | `trade_id`, `trade_version`, `status` (CONFIRMED, PENDING, AMENDED, CANCELLED), `last_modified`, unit and price fields |
| `commodities` | Full load | Small reference table |
| `books`, `counterparties` | Reference tables, changed through CDC | Current state in the source |
| `cdc_counterparties`, `cdc_books` | CDC | Operation, `lsn`, commit time |
| FX rates API | REST, date window | Public, no key |
| Wind and solar forecast API | REST, paginated | Public, no key. Half-hourly settlement periods |
| Exported files (CSV and JSON) | Files | Written by the generator to the landing zone. Used for Auto Loader and for joining file data |
| `control_totals/date=YYYY-MM-DD/control_totals.csv` | File, used for reconciliation | Row counts per day |

Tables not read by pipelines: `sim_state`, `sim_truth`, `sim_deleted_trades` and `_truth/defects.json` belong to the generator and are the answer sheet for tests.

### 5.3 Data delivery
1. The generator is written and tested in this repository and is seeded, so output is identical every time.
2. A pipeline (`simulate-source-day`) advances the source database by one business day, on demand or on a schedule.
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
Azure DevOps Pipelines: CI on pull requests, deploy Dev then Prod (approval)
        |
SOURCES                      ADF (metadata-driven)             ADLS GEN2                 DATABRICKS (shared workspace)
Shared Azure SQL             pl_ingest_generic  ---------->    landing  --------------->  Lakeflow Job (Workflow)
  etrm_dev / etrm_prod       parameters: source, load           (files as copied)          1. read control table
  trades, commodities,       type, path, run id                    |                       2. Auto Loader  -> Bronze
  cdc_counterparties,        ForEach over ctl.watermark            |                       3. schema validation
  cdc_books                                                        |                       4. Declarative Pipeline: Silver
FX rates API (REST)  ------>  REST + pagination rules              |                       5. Gold (materialized views)
Forecast API (paged) ------>                                       |                       6. checks, update control table
Files (CSV, JSON) --------->  copy to landing, or drop directly    |                       File-arrival trigger starts the job
                                                                   v
control table ctl.watermark (per environment)               bronze / silver / gold / quarantine
Secrets: Key Vault          Governance: Unity Catalog (grants per layer, row filter, column mask)
Deployment: Terraform (Azure), Databricks Asset Bundle (Databricks)
```

### 6.1 Azure resources (Terraform)
Per environment: ADLS Gen2 account with containers `landing`, `bronze`, `silver`, `gold` and `quarantine`, Key Vault (access policies), and Data Factory with linked services to Key Vault, the lake and the shared SQL database. The resource group and the shared SQL server are read, not created. The SQL server is outside this repository: the linked service reads its address, database name and login from variables, and the password is a Key Vault secret added by hand. Names are a type code, a prefix, the environment and a short suffix, for example `kv-energytrading-dev-sr`. The current code creates 13 resources for one environment.

The databases `etrm_dev` and `etrm_prod` on the shared server are created by the project (the organisation policy allows only Basic, S0 to S2 and `GP_S_Gen5_2`). `etrm_dev` was created by hand on the Basic tier. Terraform will manage the databases later.

Databricks is **not** created by Terraform: the project uses an existing shared workspace, working only in its own folders and schemas and changing no workspace settings. Dev and prod are separate schemas and job names in that workspace. The workspace sits in a different Azure region from the lake, so a small cross-region data cost is accepted.

### 6.2 Local versus Azure

| Concern | Local mode | Azure |
|---|---|---|
| Purpose | Unit tests and the generator | The real demonstration |
| Source | SQLite | Shared Azure SQL (one database per environment) |
| Ingestion | Not used | ADF |
| Compute and Delta | PySpark and Delta Lake | Azure Databricks |
| Orchestration | Not used | Lakeflow Jobs, with ADF for ingestion |
| Secrets | `.env` (ignored by git) | Key Vault, read with `dbutils.secrets` in Databricks |

Business logic that can be unit-tested (for example version selection and unit conversion) is written as plain functions in `src/lakehouse`, so it runs in both places. The Asset Bundle packages it as a Python wheel.

## 7. Layer design

### 7.1 Ingestion (ADF, metadata-driven)
The control table `ctl.watermark` holds one row per source: load type, source path or table, file format, target, an enabled flag, parameters, the watermark or last `lsn`, last status and rows loaded. One generic pipeline, `pl_ingest_generic`, reads the enabled rows and runs a ForEach. Each iteration chooses its branch by load type. Adding a source means adding a row, not a pipeline.

| Branch | Steps |
|---|---|
| WATERMARK | Lookup old watermark, copy rows after it minus the 2-day lookback, update the watermark (stored procedure, runs only after a successful copy) |
| FULL | Copy, truncate and reload, compare row counts |
| CDC | Read changes after the last `lsn`, land I, U and D rows in order, save the new `lsn` after landing |
| API | REST linked service. FX: one request per date window. Forecast: pagination rules (offset and limit, follow the `next` link until the total is reached), spaced requests. Every response is landed as raw JSON |
| FILE | Copy the file to landing, or leave it where it was written |

A failed iteration calls `ctl.usp_mark_failed`, which never moves the watermark. Pipeline parameters are `source_name`, `environment` and `run_id`. Secrets are read from Key Vault through linked services, and ADF uses a managed identity.

### 7.2 Bronze (Auto Loader)
Auto Loader (`cloudFiles`) reads the landing files incrementally and writes append-only Delta tables with audit columns (`_ingested_at`, `_source_system`, `_batch_run_id`, `_source_file`, and for CDC `_operation` and `_lsn`). It processes each new file once. No casting, renaming or filtering. Repeated rows from the lookback are expected: compare **distinct keys** with the source, not raw counts. A job with a file-arrival trigger starts the run when a file lands.

### 7.3 Schema validation
After each Bronze load, compare the incoming schema with the expected schema: columns, types and nullability. Missing or unknown columns are flagged. A failing batch is moved to quarantine and the result (pass or fail, with reasons) is recorded per batch. Auto Loader schema evolution is set to record new columns and not to change existing ones silently. Silver always selects columns explicitly, never `SELECT *`.

### 7.4 Data profiling
A time-boxed exploration of the Bronze data: row counts, null rates, value ranges, trade versions, late-arriving rows and distribution of statuses. Findings are written to `docs/data-profile.md` and drive the Silver rules.

### 7.5 Silver (Lakeflow Spark Declarative Pipelines)
Silver is one declarative pipeline of streaming tables:
1. Expectations separate valid and invalid rows. Invalid rows go to quarantine with a reason and timestamp.
2. Auto CDC applies inserts, updates and deletes and builds SCD2 history for counterparties and books.
3. Keep the highest valid `trade_version` per trade.
4. Normalise units, convert to UTC, expand to half-hourly settlement periods.
5. A pipeline update can be rerun without double counting. The job fails if the reject rate exceeds a threshold.

### 7.6 Gold (materialized views)
Gold tables are materialized views in the same pipeline: the fact and dimension tables below. Expectations and reconciliation to control totals guard publication. A failing check stops the job before the views are refreshed. dbt is not part of the core path. It can be added later as a job task (next phase).

### 7.7 Data model

| Table | Type | Grain |
|---|---|---|
| `fact_trade` | Transaction fact | One row per trade (latest valid version) |
| `fact_daily_position` | Periodic snapshot | Book x commodity x delivery period x business date |
| `dim_counterparty` | SCD2 (fed by CDC) | Counterparty x effective range |
| `dim_book` | SCD2 (fed by CDC) | Book x effective range |
| `dim_commodity`, `dim_delivery_period`, `dim_date` | Type 1 / generated | |

### 7.8 Data quality
Layered checks: row counts at landing, schema validation after Bronze, expectations in Silver, expectations and reconciliation in Gold, and daily reconciliation to control totals. Rejected rows are retained with the reason attached.

### 7.9 Orchestration (Lakeflow Jobs)
One job runs the steps in order: read the control table, Auto Loader to Bronze, schema validation, the declarative pipeline (Silver and Gold), reconciliation, then update the control table. Tasks retry on failure, pass values with task values, and a failure alert is sent. A for-each task runs one set of steps per source. The job runs on serverless compute or on a job cluster that ends when the job ends. ADF starts the job after ingestion, and a file-arrival trigger starts it when a file lands directly. Airflow is not used: ADF moves data in and Jobs run the transformations.

### 7.10 Security and governance
- **Access per layer.** Unity Catalog grants: engineers read and write Bronze and Silver, analysts read Gold only.
- **Row and column security.** A row filter limits a Gold table by desk, and a column mask hides the counterparty limit from users outside the credit group.
- **Secrets.** Key Vault only. Databricks reads them with `dbutils.secrets`, ADF with its managed identity. Nothing secret is in the repository.
- **Shared SQL server.** The shared admin password is not used by pipelines. Each environment uses its own login, limited to its own database.
- **All environments.** Security rules are the same in dev and prod. Only synthetic data exists, so nothing real is exposed in either.

### 7.11 Environments
Dev and prod have the same structure. Differences: database name, storage account and Key Vault names, Databricks schema and job names, and the approval gate before prod. Terraform has one code base, a variable file per environment and one state per environment. The Asset Bundle has a target per environment.

## 8. CI/CD and infrastructure as code

### 8.1 Continuous integration (every pull request)
Azure Pipelines run lint, unit tests, generator tests against the truth manifest, `terraform fmt` and `validate`, a `terraform plan` for dev, `databricks bundle validate`, a check that the SQL scripts run, and a secret scan. The first version (lint, tests, Terraform format and validate, and a guard against tracked state files) exists in both GitHub Actions and Azure Pipelines. GitHub Actions runs on every pull request. The Azure pipeline passed its first run and is started by hand while the project is in development.

### 8.2 Continuous delivery
Merging to `main` starts the deploy pipeline. The Dev stage runs `terraform apply` from the saved plan, applies the control-table scripts, deploys the ADF definitions and runs `databricks bundle deploy -t dev`. The Prod stage runs the same steps after a manual approval on the Azure DevOps Environment. Terraform state is stored in a remote storage account, one state file per environment. Authentication uses a service connection (workload identity federation where the organisation allows it). See [ADR 0005](decisions/0005-azure-devops-for-ci-cd.md).

### 8.3 Cost controls
Serverless SQL with auto-pause, small data volumes, serverless or auto-ending job compute, a reviewed plan before every apply, resource tags, and prod deployed only when promoted.

## 9. Acceptance criteria

1. Every implemented defect matches the truth manifest exactly.
2. Rerunning any day gives identical results for all load patterns.
3. A failed incremental load leaves the watermark unchanged, and a rerun loads everything once.
4. A CDC delete closes the dimension record without losing history.
5. The watermark blind spot (D17) is demonstrated and caught by reconciliation.
6. The paginated API pipeline loads every page of the forecast and its row count matches the reported total.
7. A new row in the control table is ingested without a new pipeline.
8. Dropping a file in the landing zone starts the job and the file is processed once.
9. A schema change in a source batch is detected after Bronze and the batch is quarantined.
10. Gold reconciles to control totals, and a deliberately broken run is blocked.
11. A row filter and a column mask change what a restricted user sees.
12. The same bundle deploys to dev and prod with different parameters.
13. A pull request runs the checks, and prod deployment waits for approval.
14. A new reader understands the system from the README in ten minutes.

## 10. Repository structure

```
README.md  LICENSE  CONTRIBUTING.md  Makefile  pyproject.toml
docs/            design, backlog, data notes, data profile, ADRs
src/lakehouse/   generator/ (done), validation/, silver/ (shared logic and tests, built as a wheel)
infra/terraform/ Azure foundation, one variable file per environment
adf/             pipeline and linked service definitions (exported JSON), sql/ control-table scripts
databricks/      notebooks, declarative pipeline files, databricks.yml and resource definitions
tests/           unit tests
pipelines/       Azure Pipelines YAML (CI and deploy)
.github/         issue and pull request templates
```

## 11. Engineering standards
`main` is protected. All changes go through pull requests with checks required. Small commits, imperative messages, short ADRs for decisions, tests before core logic. Commits are authored by the repository owner.

## 12. Verified, unverified and open items

| Item | Status |
|---|---|
| Generator and its tests (PySpark 3.5.3, Delta 3.2.1, 105 tests) | **Verified** |
| Terraform: apply, linked services, loader against Azure SQL | **Verified**. The shared-server change was planned, reviewed and applied (6 destroyed, 1 changed). The loader filled `etrm_dev` and the row counts match the source |
| Frankfurter FX API and NESO forecast API reachable without a key | **Verified** with a test call. Rate limits **not verified** |
| Control table scripts (`adf/sql`) | **Verified** in `etrm_dev`. The test script passes |
| Databricks: Unity Catalog, permission to create jobs and pipelines, serverless compute, access to the lake | **Confirmed** by the owner. Serverless compute is visible in the workspace. No Databricks code has been built yet |
| Azure DevOps: organisation, build capacity, CI pipeline | **Verified**. The pipeline builds the GitHub repository and the three checks pass. The service connection to Azure is **Open** |
| Permission to create databases on the shared SQL server | **Confirmed** by the owner |
| Lakeflow Connect for the SQL source | **Open**. Needs change tracking, a gateway and workspace permission. Next phase |

## 13. Delivery order
1. Azure foundation: Terraform with remote state, shared SQL server, dev and prod databases, source loaded
2. Control table with metadata columns, generic ADF pipeline, full load, FX API, incremental trades
3. File export in the generator, CDC, paginated forecast API
4. Databricks: lake access, Auto Loader, Bronze, schema validation, reconciliation, profiling
5. Silver and Gold (declarative pipeline), quarantine, SCD2
6. Lakeflow Job and Asset Bundle with dev and prod targets
7. Azure DevOps: CI on pull requests, staged deploy with approval
8. Security (row filter, column mask), end-to-end run and documentation
9. Next phase: Lakeflow Connect, dbt task, Airflow, Kafka real-time, price data, schema drift
