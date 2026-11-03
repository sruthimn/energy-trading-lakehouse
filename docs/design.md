# Energy Trading Lakehouse: Design Document (v0.3, approved)

Status: approved design. Implementation follows the backlog.
Repository: `sruthimn/energy-trading-lakehouse` (public, MIT licence)

---

## 0. Plain-language summary

We build a data platform for a fictional energy trading company, using synthetic data only. It runs in two modes:

- **Local mode** (free, used by automated tests): PySpark and Delta Lake on a normal machine or a CI runner.
- **Azure mode** (the real demonstration): the same code deployed to your organisation's Azure subscription with Terraform and GitHub Actions. Azure Databricks does the data processing, AKS runs Airflow and the ingestion containers, and ADLS Gen2 holds the landing files.

You run **no data generation code**. I act as the upstream source team: I generate and test the data here, and in Azure it is produced by a GitHub Actions workflow, like a real upstream system. You build and own the platform that consumes it.

## 0b. Working model: who does what

This mirrors a real project. The **source team** supplies data and contracts. The **data engineer** (Sruthi) builds the platform that consumes them.

| Area | Owner | What that means |
|---|---|---|
| Synthetic source system, generator, defect injection, truth manifest, data contracts, `simulate-source-day` workflow, sample data | **Source team (Claude)** | Sruthi never writes or runs data generation. She reviews the contracts and the change notices, as a data engineer would |
| Ingestion (full, watermark, CDC), Bronze, schema gate, Silver, Gold, data quality, orchestration, CI, Terraform, CD, AKS | **Sruthi implements, Claude pairs** | Claude explains the concept, writes the failing tests from the truth manifest, reviews, and helps when stuck. Sruthi writes and understands the pipeline code |
| Spikes and design decisions | Together | Each decision becomes a short ADR |

**Working rhythm for each issue**
1. Claude explains the concept in plain language and agrees the approach with Sruthi.
2. Claude provides the acceptance tests first (they fail).
3. Sruthi writes the implementation on a branch until the tests pass.
4. Claude reviews the pull request. Sruthi merges it.

**Development environment.** A dev container configuration is included so Sruthi can open the repository in GitHub Codespaces (or locally) with Python, Java, Spark, dbt and Terraform already installed, and commit as herself. Check the current free Codespaces allowance on your account.

**Attribution.** The git history should reflect who did the work. Code that Sruthi writes is committed as Sruthi. The synthetic data generator is written by Claude, so the README states that the generator was written with AI assistance. How the generator commits are attributed is Sruthi's decision, and I recommend being transparent about it, because interviewers may ask who wrote what.

## 1. Learning goals and where each one lives

| You want to understand | Where it lives in the project | How you demonstrate it |
|---|---|---|
| **Watermarking** | Incremental load of `trades` | Show the control table, run a failed load, rerun it, and show no data loss or duplicates |
| **Full load** | Reference data and FX | Show truncate-and-reload with a row-count guard |
| **CDC** | Counterparty and book master tables | Show inserts, updates and a delete flowing through, and the SCD2 history they create |
| **Infrastructure as code** | Terraform for Azure | `terraform plan` in a pull request, `apply` after approval, `destroy` at the end |
| **CI/CD** | GitHub Actions | A pull request runs tests, a merge builds and deploys, production needs approval |
| **AKS** | Airflow and job containers | Show pods, namespaces (dev and prod), resource limits and autoscaling |

## 2. Scope

**In scope:** synthetic data generator, three load patterns, Bronze, schema gate, Silver, Gold star schema with SCD2, data quality, Airflow orchestration on AKS, Terraform, CI/CD, real-time track, documentation.

**Out of scope:** real company data, machine learning models (a feature table is in scope), Synapse and Power BI (Gold is served from Databricks SQL).

**Portfolio honesty rule.** The README states plainly that the data is synthetic and that the project implements a pattern the author has used professionally. It quotes no production figures from any employer. The repository contains no subscription IDs, tenant IDs or organisation-specific names.

## 3. Fictional business context

*Northgate Energy Trading* (fictional) trades GB power, NBP and TTF gas, Brent crude and UK carbon allowances across several desks. Pain points the platform solves:
1. The same trade shows different volumes in different reports, because units and amendments are handled inconsistently.
2. Daily batches are fragile and dashboards are stale at the start of the trading day.
3. A monthly regulatory submission is assembled and reconciled by hand.
4. Upstream systems change their schemas without notice.
5. Credit risk needs the counterparty rating **as at the trade date**, not today.

## 4. The three load patterns (core of the project)

| Pattern | Source tables | Mechanism | Handles deletes? | Failure behaviour |
|---|---|---|---|---|
| **Full load** | `ref.commodities`, `ref.fx_rates`, `ref.calendar` | Read everything, replace, then check row count against the source | Yes (the table is replaced) | Row-count guard blocks a truncated load |
| **Incremental (watermark)** | `etrm.trades`, `etrm.trade_legs` | Read rows where `last_modified` is newer than the stored watermark minus a lookback window; advance the watermark only after success | **No** (a deleted row is invisible) | Watermark unchanged, so a rerun is safe |
| **CDC** | `ref.counterparties`, `ref.books` | Read the source change log (operation, sequence number, commit time); apply with `MERGE`; track the last sequence number | **Yes** | Last sequence number unchanged, so a rerun is safe |

A short "which pattern when, and why" page in `docs/` compares them, because interviewers ask exactly this.

**Why watermark alone is not enough.** Late-arriving rows have a `last_modified` older than the watermark, so a naive watermark misses them. The lookback window plus deduplication fixes it (defect D03). A watermark also cannot see deletes, which is why the master tables use CDC.

## 5. Source system and synthetic data

### 5.1 The simulated source
In Azure: an **Azure SQL Database** acts as the ETRM source. Native change data capture is enabled on the master tables, so CDC is real, not faked. Market and finance data arrive as daily files in a landing storage container.
In local mode: SQLite with a change-log table that follows the same contract (operation, sequence number, commit time), so the same ingestion code and tests run in CI.

*Unverified:* Azure SQL CDC depends on the service tier. We confirm this in the first spike before relying on it. The fallback is a change-log table maintained by triggers.

### 5.2 Source inventory

| Source | Load pattern | Key fields |
|---|---|---|
| `etrm.trades` | Incremental | trade_id, trade_version, book_id, commodity_code, buy_sell, volume, unit, price, currency, delivery_start, delivery_end, counterparty_id, trader_id, status, trade_date, last_modified |
| `etrm.trade_legs` | Incremental | trade_id, leg_no, volume, price |
| `ref.counterparties` | **CDC** | counterparty_id, name, credit_rating, credit_limit_gbp, country |
| `ref.books` | **CDC** | book_id, desk_code, trader_group |
| `ref.commodities`, `ref.calendar` | Full | commodity_code, standard_unit |
| `market.fx` | Full (daily file) | rate_date, currency, gbp_rate |
| `market.prices` | Daily file | curve_id, delivery_month, price_date, price |
| `finance.control_totals` | Daily file | business_date, book_id, total_volume, total_notional |
| `stream.trade_events` | Stream (phase 8) | event_id, event_type, trade_id, ... |

### 5.3 Data delivery without you running anything
1. I write and **test the generator here** and run it myself.
2. A small **sample dataset** (a few thousand rows, under a megabyte) is committed for documentation and unit tests. Large data is never committed.
3. In Azure, a **GitHub Actions workflow** (`simulate-source-day`) advances the source system by one business day, on a schedule or when you click "Run workflow". The pipeline then picks up the changes, as it would in a real project.
4. A seed makes the output identical every time.

Default cloud scale is about **20k trades per business day** to control cost. A larger scale setting exists for volume testing.

### 5.4 Defect catalogue (the generator records a truth manifest of exact counts, and tests assert the pipeline matches)

| ID | Defect | Handled by | Test |
|---|---|---|---|
| D01 | Trade amendments (versions 1 to N) | Silver keeps latest version | Equals truth |
| D02 | Cancellations | Status handling | Equals truth |
| D03 | Late-arriving rows | Watermark lookback plus dedupe | No loss, no duplicates |
| D04 | Null mandatory fields | DLQ | DLQ count equals truth |
| D05 | Delivery end before start | DLQ | Equals truth |
| D06 | Mixed units | Unit normalisation | Totals equal truth |
| D07 | Clock-change days (46 and 50 periods) | Settlement calendar | Period counts equal truth |
| D08 | Counterparty downgrade | SCD2 and as-at-trade-date join | Old trades keep old rating |
| D09 | Duplicate stream events | Idempotent by event_id | Position unaffected |
| D10 | Additive schema drift | Schema gate auto-approves | Pipeline continues |
| D11 | Breaking schema drift | Quarantine that source only | Others still publish |
| D12 | Missing FX rate | Flagged fallback | Flag count equals truth |
| D13 | Price outliers | Quality check flags | Equals truth |
| D14 | Orphan counterparty reference | Relationship test fails visibly | Fails as expected |
| D15 | Stale file re-delivered | Freshness check | Fails as expected |
| **D16** | **Counterparty deleted at source** | **CDC applies the delete, history preserved** | **Closed record, no data loss** |
| **D17** | **Hard-deleted trade row** | **Shows the watermark blind spot; reconciliation to control totals catches it** | **Variance detected** |

### 5.5 Simulated timeline
Business dates 2026-03-16 to 2026-04-10 (covers the 29 March clock change). Counterparty downgrade 2026-03-24, additive drift 2026-03-30, breaking drift 2026-04-03, counterparty deletion 2026-04-06. The autumn clock change is a separate fixture.

## 6. Architecture

```
GitHub Actions: simulate-source-day
        │ advances one business day
        ▼
SOURCES                                  AKS (Airflow + job containers)                     AZURE DATABRICKS (Unity Catalog)
Azure SQL (ETRM, CDC enabled) ─┐         ┌──────────────────────────────────┐               ┌─────────────────────────────────┐
Daily files in landing storage ─┼──────► │ ingestion containers             │ ─ landing ──► │ BRONZE   append-only, audit cols│
                                │        │  full · watermark · CDC          │  (ADLS Gen2)  │    │ schema gate (classify drift)│
                                │        │ control table (watermarks,       │               │    ▼                             │
                                │        │  last LSN, status)               │               │ SILVER   units, dedupe, DLQ      │
                                │        └──────────────────────────────────┘               │    │ dbt build + tests           │
              Airflow DAG ──────┴── triggers ingestion, Databricks jobs, dbt ───────────────►│    ▼                             │
                                                                                              │ GOLD     star schema, SCD2       │
CI/CD: GitHub Actions ──► Terraform (Azure) · Docker images (ACR) · Databricks bundle · Helm (Airflow)
Quality: Great Expectations (Bronze) · dbt tests (Gold) · reconciliation to control totals
Secrets: Key Vault · GitHub OIDC (no stored Azure passwords)
```

### 6.1 Azure resources (Terraform)
Resource group, ADLS Gen2 account (landing, quarantine), Azure Container Registry, AKS (small system pool, autoscaling user pool, `dev` and `prod` namespaces), Key Vault, Azure SQL Database (source), Azure Databricks workspace, a budget alert, and a remote Terraform state account. Private endpoints are documented but optional because of cost.

Unity Catalog: two catalogs, `lakehouse_dev` and `lakehouse_prod`, each with `bronze`, `silver`, `gold` schemas. *Open question:* a Unity Catalog metastore may already exist at your organisation, which changes how the workspace is attached (see section 12).

### 6.2 Local versus Azure

| Concern | Local mode (CI) | Azure mode |
|---|---|---|
| Source | SQLite with change-log table | Azure SQL with native CDC |
| Compute and Delta | PySpark and Delta Lake | Azure Databricks |
| Gold SQL | dbt on DuckDB | dbt on Databricks |
| Orchestration | DAG integrity test | Airflow on AKS |
| Secrets | `.env` (ignored by git) | Key Vault |

Design rule: **business logic does not depend on the platform.** Platform specifics live in thin adapters. *Risk:* dbt SQL must run on two engines. We keep models in a portable SQL subset and isolate any engine-specific code in macros (spike 0.3).

## 7. Layer design

### 7.1 Ingestion (all three patterns)
A control table holds, per source: load type, watermark or last sequence number, last run id, status and rows loaded. The ingestion container reads it, extracts, writes run-scoped Parquet to landing, and **updates the control table only after the write succeeds**.

### 7.2 Bronze
Exact append-only copy plus audit columns (`_ingested_at`, `_source_system`, `_batch_run_id`, `_source_file`, and for CDC `_operation` and `_lsn`). No casting, renaming or filtering. Bronze is the single replay point.

### 7.3 Schema evolution gate
Compare the landed schema with the registered data contract. Additive changes are registered and continue. Breaking changes (dropped, renamed, type-changed) quarantine that source, set `QUARANTINED` in the control table and alert. Silver always selects columns explicitly, never `SELECT *`.

### 7.4 Silver
1. Split valid and invalid rows (invalid go to a DLQ with reason and timestamp).
2. Apply CDC changes with `MERGE` (inserts, updates, deletes).
3. Keep the latest trade version.
4. Normalise units, convert to UTC, expand to half-hourly settlement periods.
5. Convert to GBP with flagged FX fallback.
6. Idempotent writes. Fail if the reject rate exceeds a threshold.

### 7.5 Gold (dbt)
Staging, intermediate and marts. Macros: surrogate key, safe divide, date spine, schema creation. Tests: unique, not_null, relationships, accepted_values, ranges, no overlapping SCD2 ranges, and reconciliation to control totals. A failing test blocks the publish.

### 7.6 Data model

| Table | Type | Grain |
|---|---|---|
| `fact_trade` | Transaction fact | One row per trade leg (latest version) |
| `fact_daily_position` | Periodic snapshot | Book x commodity x delivery period x business date |
| `dim_counterparty` | **SCD2** (fed by CDC) | Counterparty x effective range |
| `dim_book` | **SCD2** (fed by CDC) | Book x effective range |
| `dim_commodity`, `dim_delivery_period`, `dim_date` | Type 1 / generated | |

### 7.7 Data quality
Great Expectations on Bronze, pipeline counters on Silver, dbt tests on Gold, and daily reconciliation to control totals.

### 7.8 Orchestration
One daily Airflow DAG on AKS: ingest (per source, in parallel) → schema gate and validation → Databricks Silver jobs → dbt build → publish. Three retries with back-off, SLAs, `max_active_runs=1`, and a gate task that skips a quarantined source. DAGs synchronise from Git.

### 7.9 Governance
Pseudonymised trader identifiers (keyed hash), a masking view for price, desk-level filtering as Unity Catalog row filters, and Key Vault for secrets.

## 8. CI/CD and infrastructure as code

### 8.1 Continuous integration (every pull request)
Lint, unit tests (PySpark and Delta in local mode), generator tests against the truth manifest, dbt parse and local-mode build, DAG integrity test, `terraform fmt` and `validate`, a `terraform plan` posted to the pull request, Docker image build (no push), image vulnerability scan and a secret scan.

### 8.2 Continuous delivery (on merge to `main`)
1. Authenticate to Azure with **GitHub OIDC** (no stored Azure passwords).
2. Build and push images to the container registry.
3. Deploy the Databricks bundle to `dev` automatically.
4. **Manual approval**, then deploy to `prod`.
5. Deploy Airflow and job images to AKS with Helm.
Terraform `apply` runs from a protected workflow with an approval gate. A **destroy** workflow tears everything down.

### 8.3 Cost controls
Smallest node sizes, Databricks job clusters that terminate after each run, SQL warehouse auto-stop, an AKS stop/start workflow, a budget alert and the destroy workflow.

## 9. Acceptance criteria

1. Every defect D01 to D17 matches the truth manifest exactly.
2. Rerunning any day gives identical results, for all three load patterns.
3. A failed incremental load leaves the watermark unchanged and a rerun loads everything once.
4. A CDC delete closes the dimension record without losing history.
5. The watermark blind spot (D17) is demonstrated and caught by reconciliation.
6. A breaking schema change quarantines exactly one source while the others publish.
7. Gold reconciles to control totals, and a deliberately broken run is blocked.
8. CI passes on a pull request, and a merge deploys to `dev` automatically and to `prod` after approval.
9. `terraform apply` creates the environment and `destroy` removes it cleanly.
10. A new reader understands the system from the README in ten minutes.

## 10. Repository structure

```
README.md  LICENSE  CONTRIBUTING.md  Makefile  pyproject.toml
docs/          architecture, load patterns, data model, ADRs, runbook, cost guide
contracts/     data contracts (YAML)
src/lakehouse/ generator/ ingestion/ schema_gate/ silver/ quality/ common/ streaming/
databricks/    bundle definition, jobs
dbt/           models, macros, tests
airflow/       dags, Helm values
infra/terraform/  modules and environments
docker/        images
tests/         unit, integration, dag
.github/       workflows, issue and PR templates
sample-data/   small committed sample
```

## 11. Engineering standards
`main` is protected. All changes go through pull requests, even solo, with CI required. Small commits, imperative messages, short ADRs for decisions, tests before core logic. Commits are authored as Sruthi, with no AI trailer.

## 12. Verified, unverified and open items

| Item | Status |
|---|---|
| PySpark 3.5 with Delta Lake runs in the build environment | **Verified** |
| dbt on DuckDB reading Silver, and portable SQL across DuckDB and Databricks | **Not verified** (spike 0.3) |
| Great Expectations on Spark | **Not verified** (spike 0.4) |
| Azure SQL native CDC on the tier available to you | **Not verified** (spike 0.6) |
| Terraform, AKS, Databricks, Airflow, Helm | **Written but untested** until you run them in your subscription. I will try to validate Terraform syntax here |
| GitHub OIDC to Azure | Needs an app registration and role assignment. **Open:** can you create these, or does an administrator do it? |
| Unity Catalog metastore | **Open:** does one already exist in your tenant and region? |
| Azure policies, region and budget limits | **Open** |
| Azure Databricks cost | Depends on usage. Check the pricing calculator before the first deployment |

## 13. Delivery order (each step reviewable by pull request)

1. Foundations and spikes
2. Synthetic source system and generator (I generate and test the data)
3. Local-mode pipeline: full load, incremental, CDC
4. Silver, schema gate and data quality
5. Gold with dbt, SCD2 and reconciliation
6. CI
7. Terraform
8. CD, AKS and Airflow
9. End-to-end Azure demonstration, then teardown
10. Real-time track, documentation and results
