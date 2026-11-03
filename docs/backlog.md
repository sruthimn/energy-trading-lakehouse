# Backlog (v0.3, approved)

Each item becomes a GitHub issue once approved. Sruthi is the sole project owner. **Epic 1 is built by Claude acting as the source team. All other epics are implemented by Sruthi with Claude pairing** (concept explained first, acceptance tests provided first, code reviewed afterwards). Size: S (under half a day), M (about a day), L (2 to 3 days). Items marked **[Azure]** need your subscription and can only be marked done after you have run them.

## Epic 0: Foundations and spikes
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 0.1 | Repository setup | LICENSE (MIT), README skeleton, .gitignore, CONTRIBUTING, PR and issue templates | S |
| 0.2 | Branch protection | `main` protected, CI required | S |
| 0.3 | Spike: dbt portable across DuckDB and Databricks | ADR written, approach chosen | M |
| 0.4 | Spike: Great Expectations on Spark | ADR written | S |
| 0.5 | Project tooling | pyproject, Makefile (`setup`, `test`), pre-commit | S |
| 0.6 | **[Azure]** Spike: Azure SQL CDC on your tier | ADR written, trigger-based fallback decided if needed | S |
| 0.7 | Dev container for Codespaces and local use | Open the repository, run tests with no manual installs | S |

## Epic 1: Synthetic source system and generator (built by Claude as the source team; Sruthi reviews contracts and change notices)
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 1.1 | Reference data | Books, counterparties, commodities (fictional), seeded | S |
| 1.2 | Trades with amendments and cancellations | D01, D02 | M |
| 1.3 | Market prices and FX files | D12, D13, D15 | M |
| 1.4 | Day-by-day simulation of the source database | Advance one business day at a time; late rows (D03) | M |
| 1.5 | Change log for master tables | Operation, sequence number, commit time; D08, D16 | M |
| 1.6 | Defect injection and truth manifest | D04 to D07, D14, D17 | M |
| 1.7 | Schema drift injection | D10, D11 | S |
| 1.8 | Event stream generator | D09 | M |
| 1.9 | Generator tests and sample dataset | Determinism, manifest matches data, sample under 1 MB | M |
| 1.10 | Data contracts (YAML), reviewed and signed off by Sruthi | One per source, validated by a test | S |
| 1.12 | Change notices | A short notice for each simulated schema or data change, as a source team would send | S |
| 1.11 | **[Azure]** `simulate-source-day` workflow | Advances Azure SQL source by one day on schedule or on demand | M |

## Epic 2: Ingestion (three patterns)
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 2.1 | Control table and state module | Watermark, last sequence number, status; unit tests | M |
| 2.2 | Full load with row-count guard | Truncated source blocked | S |
| 2.3 | Incremental load with watermark and lookback | D03 handled; failed run leaves watermark unchanged | M |
| 2.4 | CDC reader | Inserts, updates, deletes in order; resumes from last sequence number | L |
| 2.5 | File feeds (prices, FX, control totals) | Freshness check catches D15 | M |
| 2.6 | Ingestion container image | Single image, one entry point per pattern | M |
| 2.7 | Documentation: which load pattern when | `docs/load-patterns.md` with worked examples | S |

## Epic 3: Bronze and schema gate
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 3.1 | Bronze writer with audit columns | Append-only Delta, CDC columns included | M |
| 3.2 | Schema classifier | Pure function, unit tests | S |
| 3.3 | Registry and gate runner | D10 approved, D11 quarantined | M |
| 3.4 | Quarantine and alerting | Batch moved, alert logged | S |

## Epic 4: Silver
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 4.1 | Valid and invalid split with DLQ | D04, D05 equal truth | M |
| 4.2 | CDC apply with MERGE | D16 handled | L |
| 4.3 | Latest version deduplication | D01 equals truth | S |
| 4.4 | Unit normalisation | D06 equals truth | M |
| 4.5 | Settlement calendar and time zones | D07 equals truth | L |
| 4.6 | FX conversion with flagged fallback | D12 equals truth | S |
| 4.7 | Idempotent writes and reject threshold | Rerun test passes | M |
| 4.8 | Pseudonymised trader identifier | Keyed hash, mapping separate | S |

## Epic 5: Gold (dbt)
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 5.1 | dbt project, macros, staging | Macros documented | M |
| 5.2 | SCD2 dimensions fed by CDC | D08, D16; no overlapping ranges | L |
| 5.3 | `fact_trade` with as-at-trade-date join | Criterion 4 and 7 | M |
| 5.4 | `fact_daily_position` | Net volume, MtM, limit utilisation | M |
| 5.5 | Generated dimensions | Date and delivery period | S |
| 5.6 | dbt tests and reconciliation | 40+ tests; D17 caught; broken run blocked | M |
| 5.7 | Regulatory submission dataset | Reconciled monthly extract | M |
| 5.8 | Feature table | Daily demand-related features | M |

## Epic 6: Data quality
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 6.1 | Bronze validation suites | D13 flagged | M |
| 6.2 | Quality report per run | Summary file | S |

## Epic 7: Continuous integration
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 7.1 | CI workflow: lint and unit tests | Runs on every pull request | M |
| 7.2 | dbt and DAG integrity checks in CI | Fails on error | S |
| 7.3 | Image build and vulnerability scan | Fails on high severity | M |
| 7.4 | Secret scan | Fails on a planted test secret | S |

## Epic 8: Infrastructure as code **[Azure]**
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 8.1 | Terraform remote state bootstrap | State account and locking | S |
| 8.2 | Core modules | Resource group, ADLS Gen2, Key Vault, container registry | M |
| 8.3 | AKS module | Small pools, `dev` and `prod` namespaces, resource quotas | L |
| 8.4 | Azure SQL source module | CDC enabled | M |
| 8.5 | Databricks workspace and Unity Catalog | Catalogs and schemas created | L |
| 8.6 | Budget alert | Alert at set thresholds | S |
| 8.7 | `terraform plan` on pull requests | Plan posted as a comment | M |
| 8.8 | Destroy workflow | Clean teardown | S |

## Epic 9: Continuous delivery and AKS **[Azure]**
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 9.1 | GitHub OIDC to Azure | No stored Azure passwords | M |
| 9.2 | Image publish workflow | Images in the registry on merge | S |
| 9.3 | Databricks bundle with dev and prod targets | Dev automatic, prod after approval | L |
| 9.4 | Airflow on AKS with Helm | DAGs sync from Git | L |
| 9.5 | Daily DAG | Retries, SLAs, quarantine gate | M |
| 9.6 | Pod limits, probes and autoscaling | Documented and demonstrated | M |
| 9.7 | AKS stop and start workflow | Saves cost between sessions | S |

## Epic 10: End-to-end demonstration and presentation
| # | Issue | Acceptance criteria | Size |
|---|---|---|---|
| 10.1 | Azure end-to-end run | All ten acceptance criteria demonstrated | L |
| 10.2 | Real-time track (file source, then Kafka) | D09 handled | L |
| 10.3 | Governance demo | Masking, desk filter | M |
| 10.4 | Architecture diagrams and README | Criterion 10 | M |
| 10.5 | Results with real run output | Numbers come from an actual run | S |
| 10.6 | Cost and teardown guide | Documented | S |

## Suggested order
Epic 0, then 1, then 2 to 6 in local mode, then 7 (CI), then 8 (Terraform), then 9 (CD and AKS), then 10.
Everything up to Epic 7 is free and testable in this session. Epics 8 to 10 need your Azure subscription and your actions.
