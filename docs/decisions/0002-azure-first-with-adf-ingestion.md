# ADR 0002: Azure first, with ADF for ingestion

- Status: accepted
- Date: 2026-11-09

## Context
The first design built ingestion as Python containers and ran everything locally first, treating Azure as documentation. The project's purpose is to demonstrate Azure data engineering: ADF, Terraform, Databricks and CI/CD. Ingestion in Python duplicated what ADF does natively (Lookup, Copy and Stored procedure activities, REST connector, pagination rules).

## Options considered
1. **Python ingestion containers on AKS.** Full control, but more code and no ADF skills demonstrated.
2. **ADF pipelines driven by a control table.** Native connectors, retries and monitoring.

## Decision
Option 2. ADF performs all ingestion: full load, watermark load, CDC and REST API pipelines (including one with pagination). Local mode (PySpark and Delta Lake) remains only for unit-testing logic and for the data generator.

Databricks uses an **existing shared workspace** and is not created by Terraform. Airflow on AKS and automated deployment move to the next phase.

## Consequences
- The Python watermark helper that was started on a branch is not needed and is dropped.
- Azure resources must exist before ingestion can be tested, so the Terraform foundation is the first deliverable.
- Pipeline definitions are exported to the repository as JSON so they are reviewed like code.
- Cost is controlled with serverless SQL (auto-pause) and small data volumes.
