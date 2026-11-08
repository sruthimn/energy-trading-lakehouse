# The change log (CDC)

This guide explains how the source system records changes to **counterparties** and **books**, and why you read a log for these two tables instead of using a watermark.

## Two ways to find out what changed

| | Watermark (trades) | Change log, called CDC (counterparties and books) |
|---|---|---|
| You ask | "Show me rows newer than my bookmark" | "Show me every change after log position 57" |
| Sees inserts and updates | Yes | Yes |
| Sees **deletes** | **No.** A deleted row simply is not there to read | **Yes.** A delete is recorded as an event |
| Sees every step of several changes in one day | No, only the latest state of the row | Yes, every change in order |
| Bookmark | The newest `last_modified` you loaded | The last **log sequence number (lsn)** you applied |

CDC stands for **change data capture**. The database itself writes the log, so the pipeline never has to guess.

## The two logs

`cdc_counterparties` and `cdc_books`. Each row is one change.

| Column | Meaning |
|---|---|
| `lsn` | Log sequence number. It only ever goes up, across both logs. It is your bookmark |
| `commit_time` | When the change was committed in the source |
| `operation` | `I` insert, `U` update, `D` delete |
| the other columns | The row **after** the change. For a delete: the row as it was just before |

Important details:
- Each log starts with one `I` for every row that already existed (the system was loaded in January 2024). So the log is **complete**. You can rebuild the whole table from the log alone, with no separate snapshot.
- `effective_from` in the tables is just an ordinary column. It is not the history. The history is the log, so use `commit_time`.
- The `lsn` order is the commit order. Always apply changes in `lsn` order, never in any other order.

## The rule that defines CDC

> Apply the log from the start, in `lsn` order: `I` adds a row, `U` replaces it, `D` removes it. The result is the current table.

A test in the project does exactly this and checks that the rebuilt table equals the real table. That is how you know the log is trustworthy, and it is how you will test your own CDC load.

## Real examples (seed 42)

### A downgrade (defect D08): CP-00002

| lsn | commit_time | operation | rating | credit limit |
|---|---|---|---|---|
| 2 | 2024-01-01 06:00:02 | I | A+ | 185,000,000 |
| 57 | 2026-03-24 10:15:00 | U | A- | 100,000,000 |

Turn this into history (SCD Type 2):

| rating | limit | valid from | valid to | current |
|---|---|---|---|---|
| A+ | 185,000,000 | 2024-01-01 | 2026-03-24 | no |
| A- | 100,000,000 | 2026-03-24 | open | yes |

A trade done on 20 March must join the first row (A+). A trade done on 25 March joins the second (A-).

### A deletion (defect D16): CP-00022

| lsn | commit_time | operation | name | rating |
|---|---|---|---|---|
| 22 | 2024-01-01 06:00:22 | I | Northcote Energy Trading Inc | A+ |
| 64 | 2026-04-06 18:30:00 | D | Northcote Energy Trading Inc | A+ |

After this, the counterparty is gone from the table, but **946 trades still point to it**. If your pipeline deleted the dimension row, those trades would lose their counterparty and the history would be wrong. The right approach is to **close** the record (give it an end date and mark it as deleted) and keep it.

No new trade is created for this counterparty after its deletion. The deletion is at 18:30, after trading hours.

### A book moved between desks: BK-UKGAS-03

| lsn | commit_time | operation | desk |
|---|---|---|---|
| 49 | 2024-01-01 06:00:49 | I | UKGAS |
| 55 | 2026-03-19 09:00:00 | U | EUGAS |

Profit and loss must be assigned to the desk that owned the book **at the time**, so this needs history, just like the rating.

## What else happens in the log

| Date | What | Defect |
|---|---|---|
| 19 Mar 2026 | A book moves desk | history needed |
| 24 Mar 2026 | A counterparty is downgraded and its limit cut | D08 |
| 26 Mar 2026 | A new counterparty, CP-00041, is onboarded (an insert). New trades start using it the next day | |
| 6 Apr 2026 | A counterparty is deleted | D16 |
| Most days | Small random changes: a limit adjusted, or a rating moves one notch | |

Over the first 18 business days, the counterparty log holds 54 rows: 41 inserts, 12 updates and 1 delete.

## Rules for your CDC load
1. Remember the **last lsn** you applied. Next time, read only rows with a larger lsn.
2. Move that bookmark only **after** a successful write (same safety rule as the watermark).
3. Apply changes in lsn order.
4. If two changes hit the same row in one batch, the later lsn wins.
5. Re-running the same batch must give the same result. (Think about how you would make that true.)

## Try it
In a Codespace, after merging:

```bash
python -m lakehouse.generator.cli init --dir data/source --trades-per-day 2000
python -m lakehouse.generator.cli advance --dir data/source --days 18
sqlite3 data/source/etrm.db "select * from cdc_counterparties where counterparty_id = 'CP-00002' order by lsn"
```
