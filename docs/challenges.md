# Challenges log

This page lists the data and design challenges in the project: what each one is, where it appears, and how the pipeline handles it.

Statuses in Part 1 describe the generator: **Injected** means the defect is in the source data, **Planned** means it is not built yet. Part 2 describes the pipeline: **Planned** until it is built and tested.

---

## Part 1: Data challenges (the defects)

The generator injects these deliberately. The truth manifest (`_truth/defects.json`) records exactly which rows are affected, so tests can show that the pipeline catches each one. See [docs/data/truth-manifest.md](data/truth-manifest.md).

| ID | Challenge | Where it appears | Required handling | Status |
|---|---|---|---|---|
| D01 | Amended trades: every change writes a new version row | `trades`, versions 2 to 5 | Keep the highest `trade_version` per trade. Never add versions together | Injected |
| D02 | Cancelled trades: a final row with status `CANCELLED` | `trades` | Keep the row, exclude it from positions | Injected |
| D03 | Late-arriving rows: the row reaches the database a day after its `last_modified` | `trades`, about 0.5% of new trades | Read from before the watermark (a lookback), then remove repeats | Injected |
| D04 | Empty mandatory field | `trades`, about 0.05% of rows | Quarantine with a reason. Do not fail the job | Injected |
| D05 | Delivery period ends before it starts | `trades`, about 0.02% of rows | Quarantine with a reason | Injected |
| D06 | Mixed units (MW, MWh, therm, bbl, m3) | About a quarter of trades | Convert to a standard unit per commodity | Injected |
| D07 | Clock changes: 23 and 25 hour days, 46 and 50 settlement periods | Power trades whose period crosses 29 March or 25 October | Convert to UTC before measuring a period. A March delivery month has 743 hours, not 744 | Injected |
| D08 | Counterparty downgrade (rating and limit change) | `cdc_counterparties`, 24 March | Keep both versions (SCD Type 2). Join a trade to the version valid on its trade date | Injected |
| D09 | Duplicate stream events | Event stream | Idempotent processing by `event_id` | Planned |
| D10 | Additive schema change (a new column) | A source table or file | Record the change and continue | Planned |
| D11 | Breaking schema change (type changed or column dropped) | A source table or file | Quarantine that batch only. Others still publish | Planned |
| D12 | Missing FX rate | FX rates | Use the previous rate and flag it | Planned |
| D13 | Price outliers | Price file | Flag, do not accept silently | Planned |
| D14 | Orphan counterparty: a trade points to a counterparty that does not exist | `trades`, about 0.02% of new trades | Keep the trade. The relationship test flags it | Injected |
| D15 | Stale file re-delivered | Price file | Freshness check fails | Planned |
| D16 | Counterparty deleted at the source | `cdc_counterparties`, 6 April | Close the record and keep history, because 946 trades still point to it | Injected |
| D17 | Trades physically deleted (5 trades on 2 April) | `trades` | A watermark cannot see this. Daily reconciliation to the control totals catches it | Injected |

---

## Part 2: Design challenges

| Challenge | The problem | Approach | Status |
|---|---|---|---|
| Late data and the watermark | A row with an old `last_modified` is never read | A lookback window per source, based on how late data actually arrives. The watermark moves forward only after success | Planned |
| Repeats created by the lookback | The lookback reads the same rows twice | Append to Bronze and remove repeats in Silver (ADR 0001). At large scale, an insert-only merge on the key | Decided |
| Cost of the lookback at scale | Wasted volume per day is lookback days times daily volume | A per-source lookback, narrow windows, partition pruning, CDC where available | Understood |
| Safe reruns (idempotency) | A repeated or half-failed run must not double or lose data | Move the bookmark only after a successful write. Overwrite a partition or merge on a key | Planned |
| Deletes at the source | A watermark cannot see deleted rows | CDC change log, or reconciliation to control totals | Planned |
| CDC ordering | Changes must be applied in order | Apply by log sequence number (`lsn`). The later `lsn` wins. The last `lsn` applied is the bookmark | Planned |
| History (SCD Type 2) | Overwriting a rating rewrites the past | One row per change with valid-from and valid-to dates. A fact stores the key of the version valid on its date | Planned |
| Keeping the latest version | Several rows per trade | `row_number() over (partition by trade_id order by trade_version desc)`, after separating valid from invalid rows | Planned |
| Bad data: fail or quarantine | One bad row must not stop the whole job | Quarantine with a reason. Fail only if the reject rate is above a threshold | Planned |
| Schema changes | Sources change without notice | Schema validation after Bronze compares columns, types and nullability. Failing batches are quarantined | Planned |
| REST API pagination | An API returns a large result in pages | ADF pagination rules: offset and limit, or follow the `next` link, until the reported total is reached. Row counts are validated | Planned |
| API rate limits and availability | Public APIs limit requests and can change | Space requests, retry with back-off, retain raw responses, validate the schema | Planned |
| Time zones | Local times and clock changes | Convert to UTC early and count real hours | Planned |
| Units | The same quantity in several units | One standard unit per commodity with fixed factors, applied in Silver | Planned |
| Reconciliation | Confirming the numbers are right | Compare Gold totals to the control totals every day. Block publication if they differ | Planned |
| Orchestration | Dependencies, retries, deadlines | ADF triggers first. Airflow on AKS with retries, SLAs and a gate for quarantined sources in the next phase | Planned |
| Infrastructure as code | Portal changes are not repeatable | Terraform in Git, a reviewed plan before every apply, destroy when finished | Planned |
| CI/CD | Untested code reaches production | Tests and checks on every pull request. Automated deployment in the next phase | Planned |
| Secrets and access | Passwords in code are a breach | Key Vault, managed identity. Nothing secret in the repository | Planned |
| Shared workspace | The Databricks workspace is shared with other teams | Own folder and schema only. No changes to workspace settings | Planned |
| Cost control | Cloud bills grow quietly | Serverless SQL with auto-pause, small data volumes, a reviewed plan, destroy when finished | Planned |

---

## Part 3: Open decisions

| Decision | Status | Notes |
|---|---|---|
| Bronze: append or merge | Decided: append with a lookback | ADR 0001. Revisit at large scale |
| Size of the lookback | 2 days for trades | Configured as a pipeline parameter |
| Shared Databricks workspace access to the lake | Open | To be confirmed before Bronze work starts |
| dbt against the shared workspace (SQL warehouse or cluster) | Open | To be confirmed before Gold work starts |
| Rate limits of the NESO forecast API | Open | Check before building the paginated pipeline |
| Real-time track (Kafka) | Next phase | After the batch pipeline |
