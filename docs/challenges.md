# Challenges log

Every real data project has problems that are easy to miss and hard to explain later. This page lists the ones in this project: what each is, where it appears in the data, how we handle it, and how to talk about it in an interview.

**How to use it**
- Before you build a part, read its row. After you build it, update the status.
- Statuses: **Planned** (not built), **In the data** (the source team has injected it), **Learned** (understood by hand), **Built** (handled in the pipeline and tested).
- The "In an interview" lines are short answers. Only say "I did this" for what you really built. For the rest, say "the pattern I would use".

---

## Part 1: Data challenges (the defects)

The source team injects these on purpose. The truth manifest (`_truth/defects.json`) records exactly which rows are affected, so tests can prove the pipeline catches each one. See `docs/data/truth-manifest.md`.

| ID | Challenge | Where it appears | What the pipeline must do | Status |
|---|---|---|---|---|
| D01 | **Amended trades**: every change writes a new version row | `trades`, versions 2 to 5 | Keep the highest `trade_version` per trade. Never add versions together | In the data, Learned |
| D02 | **Cancelled trades**: a final row with status `CANCELLED` | `trades` | Keep the row, but exclude it from positions | In the data |
| D03 | **Late-arriving rows**: the row reaches the database a day after its `last_modified` | `trades`, about 0.5% of new trades | Read from before the watermark (a lookback), then remove repeats | In the data, Learned (by hand) |
| D04 | **Empty mandatory field** | `trades`, about 0.05% of rows | Dead letter queue (DLQ) with a reason, do not fail the job | In the data |
| D05 | **Delivery period ends before it starts** | `trades`, about 0.02% of rows | DLQ | In the data |
| D06 | **Mixed units** (MW, MWh, therm, bbl, m3) | About a quarter of trades | Convert to a standard unit per commodity | In the data |
| D07 | **Clock changes**: 23 and 25 hour days, 46 and 50 settlement periods | Power trades in MW whose period crosses 29 Mar or 25 Oct | Convert to UTC before measuring a period. A March delivery month has 743 hours, not 744 | In the data |
| D08 | **Counterparty downgrade** (rating and limit change) | `cdc_counterparties`, 24 Mar | Keep both versions (SCD Type 2). Join a trade to the version valid on its trade date | In the data |
| D09 | **Duplicate stream events** | Event stream (planned) | Idempotent processing by `event_id` | Planned |
| D10 | **Additive schema change** (a new column) | A source file or table (planned) | Register the column and carry on | Planned |
| D11 | **Breaking schema change** (type changed or column dropped) | A source file or table (planned) | Quarantine that source only. Others still publish | Planned |
| D12 | **Missing FX rate** | FX file (planned) | Use the previous rate and flag it | Planned |
| D13 | **Price outliers** | Price files (planned) | Flag, do not silently accept | Planned |
| D14 | **Orphan counterparty**: a trade points to a counterparty that does not exist | `trades`, about 0.02% of new trades | Keep the trade. The relationship test must flag it | In the data |
| D15 | **Stale file re-delivered** | Price files (planned) | Freshness check fails | Planned |
| D16 | **Counterparty deleted at the source** | `cdc_counterparties`, 6 Apr | Close the record. Keep history, because 946 trades still point to it | In the data |
| D17 | **Trades physically deleted** (5 trades on 2 Apr) | `trades` | A watermark cannot see this. Daily reconciliation to the control totals catches it | In the data |

---

## Part 2: Design challenges (the hard questions)

| Challenge | The problem in one line | How we handle it | In an interview | Status |
|---|---|---|---|---|
| **Late data vs a watermark** | A row with an old `last_modified` is never read | Lookback window, set per source, based on how late data really arrives | "The watermark moves forward only after success, and we start a little before it to catch late rows. Repeats are removed later." | Learned, coding now |
| **Repeats created by the lookback** | The lookback reads the same rows twice | Append to Bronze, remove in Silver (ADR 0001). At large scale: an insert-only merge on the key | "At small scale append and clean in Silver. At terabytes per day I would narrow the window and only insert new keys, pruned to recent partitions." | Decided, see ADR 0001 |
| **Cost at scale** | Wasted data per day is lookback days times daily volume | Per-source lookback, narrow windows, partition pruning, CDC where available | See above | Understood |
| **Safe to rerun (idempotency)** | A repeated or half-failed run must not double data or lose it | Move the bookmark only after a successful write. Overwrite a partition or merge on a key | "Every task can be run twice with the same result." | Planned |
| **Deletes at the source** | A watermark cannot see deleted rows | CDC change log, or compare to control totals | "Incremental loads miss hard deletes, so I use CDC or reconcile." | In the data |
| **CDC ordering** | Changes must be applied in order | Apply by log sequence number (`lsn`). The later `lsn` wins | "I keep the last `lsn` I applied as the bookmark." | Planned |
| **History (SCD Type 2)** | Overwriting a rating rewrites the past | New row per change, with valid-from and valid-to dates. A fact stores the key of the version valid on its date | "Credit risk needs the rating as at the trade date." | Learned |
| **Keeping the latest version** | Several rows per trade | A window function: `row_number() over (partition by trade_id order by trade_version desc)` | "I split valid and invalid rows first, then keep the highest version." | Learned |
| **Bad data: fail or quarantine?** | One bad row must not stop the whole job | DLQ with a reason. Fail only if the reject rate is above a threshold | "Rows go to a dead letter table. The job fails only above 0.1%." | Planned |
| **Schema changes** | Sources change without notice | Additive: auto-approve. Breaking: quarantine that source, alert, others continue | "Detect, classify, contain." | Planned |
| **Time zones** | Local times and clock changes | Convert to UTC early. Count real hours | "A March month has 743 hours." | In the data |
| **Units** | The same quantity in several units | One standard unit per commodity, using fixed factors | "Normalise in Silver, never in Gold." | In the data |
| **Reconciliation** | How do you know the numbers are right? | Compare Gold totals to the control totals every day. Block the publish if they differ | "A variance above the tolerance blocks the regulatory dataset." | Planned |
| **Orchestration** | Dependencies, retries, deadlines | Airflow: retries with backoff, SLAs, skip one quarantined source, run the rest | "ADF moves data, Airflow conducts." | Planned |
| **Environments** | Dev must not break prod | Separate dev and prod, approval before prod | "Deploy dev automatically, prod after approval." | Planned |
| **Infrastructure as code** | Clicking in the portal is not repeatable | Terraform in Git, plan on pull request, apply after approval, destroy when done | "No manual changes in the portal." | Planned |
| **CI/CD** | Untested code reaches production | Tests on every pull request. Build, deploy, approve | "Nothing merges unless the checks pass." | Planned |
| **Containers and AKS** | Consistent environments, scaling | One image for dev and prod. Resource limits, health probes, autoscaling | "The same image runs everywhere." | Planned |
| **Secrets and access** | Passwords in code are a breach | Key Vault, managed identity, GitHub OIDC. Nothing secret in the repository | "No secrets in Git, ever." | Planned |
| **Privacy** | Trader names are personal data | Pseudonymise with a keyed hash, restrict the mapping | "Minimise, pseudonymise, restrict." | Planned |
| **Cost control** | Cloud bills grow quietly | Small sizes, auto-stop, budget alerts, a destroy workflow | "A budget alert on day one." | Planned |

---

## Part 3: Problems we met while building (real stories)

These actually happened in this project. They make good interview stories because they are true and specific.

| What happened | Cause | What we did | Lesson |
|---|---|---|---|
| Documentation files were missing from a commit | A `.gitignore` rule for `data/` also matched `docs/data/` | Anchored the rule to the top-level folder | An overly broad ignore rule hides files silently. Check the file list in every commit |
| The first full run failed with a "NOT NULL" error | A schema edit matched the wrong table | Corrected the table and re-ran at full size | A test on a small sample would not have caught it. Run at real size |
| A March delivery month came out one hour too long | Clock times were subtracted directly, ignoring the clock change | Converted to UTC first | Subtracting local times is wrong across clock changes |
| A test failed at a high defect rate | The test assumed a later version could not also be spoiled | Skipped rows that were injected separately | Check what a test assumes before blaming the code |
| `make test` failed in a fresh Codespace ("No module named pytest") | The automatic setup did not finish | Ran `make setup` by hand | Environments need a checked first-run path |
| `apt` could not find the package | The package list was stale and I had given a wrong spelling | `sudo apt-get update`, or use the Python alternative | Read the exact error before guessing |
| The pull request tool refused ("must be a collaborator") | The automation was linked to a different GitHub account | Created pull requests from the branch link | Check which identity automation runs as |
| An app could not open a file | The file was outside the folder the app may read | Copied the guides into the allowed folder | Tools have boundaries. Know them |
| A confusing word | I used "version" for hours without defining it | Defined it. The rule now: ask the first time a word is unclear | Unclear words cost more the longer they last |

---

## Part 4: Open decisions

| Decision | Status | Notes |
|---|---|---|
| Bronze: append or merge | **Decided: append, with a lookback** | ADR 0001. Revisit at large scale |
| Size of the lookback | Starts at 2 days for trades | Should come from the source team's data contract |
| Azure permissions, Unity Catalog metastore, budget and policy limits | **Open** | Needs your lead. Not needed yet |
| Real-time track (Kafka) | Later | After the batch pipeline |
| Visibility of the repository | Public | No employer names or figures |

---

## Part 5: Your practice list

Questions to answer in your own words, when you are ready. Interviewers ask these.

- [x] Why do we keep Bronze unchanged?
- [x] Why keep only the latest version of a trade?
- [x] Why join a trade to the counterparty rating as at the trade date?
- [x] What is the difference between `trade_version` and `last_modified`?
- [x] What goes wrong with a plain watermark and late data?
- [ ] Why can a watermark never see a deleted counterparty, while a change log can?
- [ ] Why are the control totals needed if the load copies every new row?
- [ ] A 10 MW power trade for March 2026: how many MWh, and why not 7,440?
- [ ] Version 1 valid, version 2 with an empty volume: which version counts?
- [ ] What is the cost of a lookback, and how do you reduce it at scale?
