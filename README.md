# Energy Trading Lakehouse

An end-to-end data engineering platform for a **fictional** energy trading company, built on Azure with a Medallion (Bronze, Silver, Gold) lakehouse. It demonstrates four ingestion patterns (full load, watermark incremental load, change data capture and REST API ingestion with pagination), schema validation, data quality checks, an SCD Type 2 star schema, infrastructure as code and CI/CD.

> **Status:** in progress. The synthetic source system is complete. The Azure environment and ingestion pipelines are being built. See [docs/design.md](docs/design.md) and [docs/backlog.md](docs/backlog.md).

## About the data

Trading data is **synthetic**, and two public APIs supply FX rates and a grid forecast. No real company data, system names or figures are used. The synthetic source system and data generator were written with AI assistance. The platform that consumes the data (ingestion, Bronze, Silver, Gold, quality, CI/CD and infrastructure) is the author's work.

This project implements a pattern the author has used professionally. It does not quote production figures from any employer.

## What this project demonstrates

| Topic | Where to look |
|---|---|
| Watermark incremental load with a lookback | ADF pipeline for `trades` |
| Full load with a row-count check | ADF pipeline for `commodities` |
| Change data capture (inserts, updates, deletes) | ADF pipeline for counterparty and book change logs |
| REST API ingestion and pagination | ADF pipelines for FX rates and the grid forecast |
| Schema validation with quarantine | After Bronze |
| SCD Type 2 and as-at-trade-date joins | Gold dimensions |
| Infrastructure as code | Terraform for Azure |
| CI | GitHub Actions |

## Architecture

Azure SQL (synthetic source) and two public REST APIs feed Azure Data Factory. Data lands in ADLS Gen2 and flows through Bronze and Silver on Azure Databricks, then Gold models built with dbt. Terraform provisions the Azure resources, Key Vault holds the secrets and GitHub Actions checks every change. Airflow on AKS, automated deployment and a real-time track are planned for a later phase. Details are in [docs/design.md](docs/design.md) and the decisions are in [docs/decisions](docs/decisions).

## Getting started (local)

Local mode runs the data generator and the unit tests. It needs Python 3.11 and Java 17 (for Spark).

```bash
make setup
make test
```

`make test-fast` skips the tests that start Spark. A dev container for GitHub Codespaces is included in `.devcontainer/` as an alternative.

To create and advance a synthetic source system, see [docs/data/source-database.md](docs/data/source-database.md).

## Contributing

This is a personal learning and portfolio project. See [CONTRIBUTING.md](CONTRIBUTING.md) for the working conventions.

## Licence

MIT. See [LICENSE](LICENSE).
