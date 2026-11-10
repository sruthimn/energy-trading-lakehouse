# Energy Trading Lakehouse

An end-to-end data engineering platform for a **fictional** energy trading company, built on Azure and Databricks with a Medallion (Bronze, Silver, Gold) lakehouse. It demonstrates metadata-driven ingestion with Azure Data Factory (full load, watermark incremental load, change data capture, REST API ingestion with pagination, and files), Auto Loader, Lakeflow Spark Declarative Pipelines, Databricks Workflows and Asset Bundles, data quality checks, an SCD Type 2 star schema, row and column security, infrastructure as code, and CI/CD with dev and prod environments in Azure DevOps.

> **Status:** in progress. The synthetic source system is complete and the Azure foundation has been deployed once. The control table, ingestion pipelines, Databricks layers and deployment pipelines are being built. See [docs/design.md](docs/design.md) and [docs/backlog.md](docs/backlog.md).

## About the data

Trading data is **synthetic**, and two public APIs supply FX rates and a grid forecast. No real company data, system names or figures are used. The synthetic source system and data generator were written with AI assistance. The platform that consumes the data (ingestion, Bronze, Silver, Gold, quality, CI/CD and infrastructure) is the author's work.

This project implements a pattern the author has used professionally. It does not quote production figures from any employer.

## What this project demonstrates

| Topic | Where to look |
|---|---|
| Metadata-driven, parameterised ingestion | One generic ADF pipeline driven by a control table |
| Watermark incremental load with a lookback | The `trades` source |
| Full load with a row-count check | The `commodities` source |
| Change data capture (inserts, updates, deletes) | Counterparty and book change logs |
| REST API ingestion and pagination | FX rates and the grid forecast |
| File ingestion with Auto Loader | CSV and JSON files in the landing zone |
| Schema validation with quarantine | After Bronze |
| Declarative pipelines, SCD Type 2, as-at-trade-date joins | Silver and Gold |
| Workflows and Asset Bundles | One job, deployed to dev and prod |
| Row and column security | Unity Catalog on a Gold table |
| Infrastructure as code | Terraform for Azure |
| CI/CD | Azure DevOps Pipelines, with an approval before prod |

## Architecture

A shared Azure SQL server (synthetic source), two public REST APIs and files feed Azure Data Factory, which is driven by a control table. Data lands in ADLS Gen2. Azure Databricks reads it with Auto Loader and builds Bronze, Silver and Gold with Lakeflow Spark Declarative Pipelines, run by a Lakeflow Job and deployed with a Databricks Asset Bundle. Terraform provisions the Azure resources, Key Vault holds the secrets and Azure DevOps Pipelines deploy every change to dev and then prod. Lakeflow Connect, dbt, Airflow on AKS and a real-time track are planned for a later phase. Details are in [docs/design.md](docs/design.md) and the decisions are in [docs/decisions](docs/decisions).

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
