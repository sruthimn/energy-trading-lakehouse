# ADR 0004: Shared SQL server and separate dev and prod environments

- Status: accepted
- Date: 2026-11-09

## Context
The first Terraform version created its own SQL server for the simulated source. The organisation provides a shared SQL server for training projects and asks that small projects use it to keep costs down. The project also needs dev and prod environments.

## Options considered
1. **Keep the project's own SQL server.** Full control, but a second server for the organisation to pay for.
2. **One database on the shared server, schemas for dev and prod.** Cheapest, but the environments are weakly isolated.
3. **One database per environment on the shared server.** Better isolation at a small extra cost, with small databases.

## Decision
Option 3. The project's own server is removed. The databases `etrm_dev` and `etrm_prod` live on the shared server. `etrm_dev` was created by hand in the portal on the Basic tier, because the organisation policy allows only Basic, S0 to S2 and `GP_S_Gen5_2`. `etrm_prod` and management by Terraform come later. The server itself is outside this repository: Terraform only reads its address, and the linked service takes the server address, database name and login from variables. Pipelines use a project login limited to its own database, not the shared administrator. Its password is a Key Vault secret added by hand.

Terraform has one code base, a variable file per environment and one state per environment. Storage, Key Vault and Data Factory exist for each environment. The shared Databricks workspace cannot be duplicated, so dev and prod are separate schemas and job names in it.

## Consequences
- The server name, address and administrator are never committed. They live in an ignored variable file.
- The server firewall belongs to its owner, so access from a developer machine must be requested.
- The shared server is in a different resource group and region from the project, so Terraform needs rights to create databases there.
- Deleting the old server removes the data loaded into it. The generator can load it again.
- Prod is deployed only when promoted, to keep costs small.
- The Basic tier has 5 DTUs and a 2 GB limit, so it is slow for heavy queries. `S0` is the next allowed size if the data grows.
