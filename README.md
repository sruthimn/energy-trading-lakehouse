# Energy Trading Lakehouse

An end-to-end data engineering platform for a **fictional** energy trading company, built on a Medallion (Bronze, Silver, Gold) lakehouse. It demonstrates three load patterns (full load, incremental with a watermark, and change data capture), schema-evolution control, data quality gates, an SCD Type 2 star schema, orchestration on Kubernetes, infrastructure as code and CI/CD.

> **Status:** early stage. The design is approved and the build is in progress. See [docs/design.md](docs/design.md) and [docs/backlog.md](docs/backlog.md).

## About the data

All data in this repository is **synthetic**. No real company data, system names or figures are used. The synthetic source system and data generator were written with AI assistance. The platform that consumes the data (ingestion, Bronze, Silver, Gold, quality, orchestration, CI/CD and infrastructure) is the author's work.

This project implements a pattern the author has used professionally. It does not quote production figures from any employer.

## What this project demonstrates

| Topic | Where to look |
|---|---|
| Watermark-based incremental loading | Ingestion of `trades` (planned) |
| Full load with row-count guard | Reference data (planned) |
| Change data capture (inserts, updates, deletes) | Counterparty and book master tables (planned) |
| Schema evolution gate with quarantine | Between Bronze and Silver (planned) |
| SCD Type 2 and as-at-trade-date joins | Gold dimensions (planned) |
| Infrastructure as code | Terraform for Azure (planned) |
| CI/CD | GitHub Actions (planned) |
| Airflow on Kubernetes | AKS (planned) |

## Architecture (planned)

Azure Databricks with Delta Lake for processing, ADLS Gen2 for landing files, Airflow on AKS for orchestration, dbt for the Gold layer, Terraform and GitHub Actions for deployment. A local mode (PySpark and Delta Lake) runs the same logic in automated tests at no cost. Details are in [docs/design.md](docs/design.md).

## Getting started

Instructions will be added as the first working components land.

## Contributing

This is a personal learning and portfolio project. See [CONTRIBUTING.md](CONTRIBUTING.md) for the working conventions.

## Licence

MIT. See [LICENSE](LICENSE).
