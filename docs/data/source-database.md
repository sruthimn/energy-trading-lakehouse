# The source database

This is the fictional trading system that your pipeline reads from. It is a small SQLite file called `etrm.db`. (ETRM is the usual name for a trading system.)

It moves forward **one business day at a time**, like a real system. You decide when the next day happens. This is what lets you run your pipeline day after day and watch the watermark move.

## The commands

```bash
# 1. Create a new source system (once)
python -m lakehouse.generator.cli init --dir data/source --trades-per-day 1000

# 2. Simulate the next business day (as many times as you like)
python -m lakehouse.generator.cli advance --dir data/source

# 3. Simulate several days at once
python -m lakehouse.generator.cli advance --dir data/source --days 5

# 4. See where it is
python -m lakehouse.generator.cli status --dir data/source
```

Use `--trades-per-day 20000` for the larger demo size. At that size one day takes about one second.

The `data/` folder is ignored by git, so the database is never committed. Only the small sample dataset will be committed later.

## It remembers where it stopped

You can close everything and run `advance` tomorrow. It carries on from the next business day. Two runs with the same settings always give identical data, and a run in two halves gives the same data as a run straight through. Tests check this.

## Tables you may read

| Table | What it holds | How the pipeline should load it |
|---|---|---|
| `trades` | Every version of every trade | **Incremental, using a watermark on `last_modified`** |
| `books` | The portfolios | **CDC**, using `cdc_books` |
| `commodities` | What can be traded | Full load |
| `counterparties` | The companies we trade with | **CDC**, using `cdc_counterparties`. The table itself shows only the current state |

| `cdc_counterparties`, `cdc_books` | The change logs: every insert, update and delete | Read in `lsn` order. See `docs/data/change-log-cdc.md` |

`commodities` is the only table loaded in full. Dates are stored as text: `2026-03-16 14:05:31` for times and `2026-03-16` for dates.

## Files the source also writes

| File | What it is |
|---|---|
| `control_totals/date=YYYY-MM-DD/control_totals.csv` | The end-of-day totals per book, as a finance extract. You reconcile Gold against it |

## The data is not clean

The `trades` table accepts empty values in `book_id`, `commodity_code`, `volume`, `unit` and `delivery_start`, as many real systems do. About 0.05% of rows have one empty, 0.02% have a delivery period that ends before it starts, and 0.02% of new trades point to a counterparty that does not exist. Five old trades are deleted on 2 April. See `docs/data/truth-manifest.md`.

## Tables you must not read

`sim_state`, `sim_truth` and `sim_deleted_trades` belong to the simulator, not to the trading system. They hold the simulator's progress and a private record of what was injected, used by tests. A real pipeline would not have access to them, so yours must not use them.

## The first problem you will meet: late rows (defect D03)

About 0.5% of new trades reach the database **a day late**. The deal was done yesterday morning, and its `last_modified` says yesterday morning, but the row only appears today.

Here is why that hurts a watermark:

1. After yesterday's load, your watermark is the newest `last_modified` you saw, for example `2026-03-16 17:29:59`.
2. Today a late row arrives with `last_modified = 2026-03-16 09:41:12`.
3. Your next load asks for rows where `last_modified` is **greater than the watermark**.
4. `09:41:12` is not greater than `17:29:59`, so the row is **never loaded**. No error appears. The data is simply missing.

A test in the project shows exactly this. Your load must be designed to catch such rows. That is the main reason watermark loads use a **lookback window**: they start a little before the watermark, then remove duplicates afterwards.

Example from a full-size run (20,000 trades per day):

| Day | Rows added | New | Amended | Cancelled | Late |
|---|---|---|---|---|---|
| 16 Mar | 20,000 | 20,000 | 0 | 0 | 0 |
| 17 Mar | 20,510 | 20,000 | 407 | 103 | 72 |
| 18 Mar | 21,045 | 20,000 | 863 | 182 | 103 |
| 19 Mar | 21,706 | 20,000 | 1,448 | 258 | 121 |
| 20 Mar | 22,520 | 20,000 | 2,153 | 367 | 98 |

The first day has no late rows, because there is no "yesterday" yet. Amendments and cancellations build up over the first week, because they refer to earlier trades.

## What is not here yet

- Market price and FX files, with missing rates and outliers (issue #10).
- Schema changes (issue #14).
- The event stream (issue #15).
