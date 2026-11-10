# ADR 0003: Databricks-native processing, orchestration and deployment

- Status: accepted
- Date: 2026-11-09

## Context
ADR 0002 chose ADF for ingestion and left Bronze and Silver to Databricks notebooks, Gold to dbt and orchestration to ADF triggers, with Airflow later. The target environment is heavily Databricks-based, and Databricks now provides tools for each of these steps: Auto Loader, declarative pipelines, Workflows and Asset Bundles.

## Options considered
1. **Notebooks, dbt for Gold, Airflow for orchestration.** Familiar, but three tools for one flow, and the project would not show the platform's own tooling.
2. **Databricks-native.** Auto Loader for file ingestion, Lakeflow Spark Declarative Pipelines for Bronze to Gold, Lakeflow Jobs for orchestration and Asset Bundles for deployment.

## Decision
Option 2.
- Auto Loader reads files from the landing zone incrementally.
- Silver and Gold are a declarative pipeline (formerly Delta Live Tables), with expectations for data quality and Auto CDC for SCD2.
- A Lakeflow Job runs the steps, with retries, a file-arrival trigger and alerts. ADF starts it after ingestion.
- A Databricks Asset Bundle deploys the job and pipeline. It builds a Python wheel from `src` and defines dev and prod targets.
- `dbutils` provides widgets, secrets and file utilities in notebooks.
- dbt and Airflow leave the core. dbt may return as a job task, and Airflow stays a next-phase item.
- Lakeflow Connect is a next-phase item, because the managed SQL Server connector needs change tracking, a gateway and workspace permissions that a shared workspace may not allow.

## Consequences
- One platform runs transformations and orchestration. ADF stays for movement into the lake.
- Unit-testable logic lives in `src/lakehouse` and is shipped as a wheel.
- Gold uses materialized views, so a failed check must stop the job before the views refresh.
- What the shared workspace allows (Unity Catalog, jobs, pipelines, serverless) must be confirmed before work starts, and the plan may change if something is blocked.
