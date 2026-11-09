# ADR 0001: Bronze is append-only, with a lookback window

- Status: accepted
- Date: 2026-11-10

## Context
Trades are loaded incrementally with a watermark on `last_modified`. About 0.5% of new trades arrive a day late (defect D03). Their `last_modified` is older than the watermark, so a plain watermark never loads them, and nothing reports an error.

Going back before the watermark (a lookback window) catches those rows. The cost is that rows loaded on earlier days are read again.

## Options considered
1. **Append everything, remove repeats in Silver.** Bronze keeps every load as it arrived.
2. **Insert only new keys into Bronze** (an insert-only merge on `trade_id` and `trade_version`, limited to recent partitions). Bronze holds each source row once.

## Decision
**Option 1 for now: append to Bronze, tag each row with its batch, and keep the highest valid version of each trade in Silver.**

The lookback is applied in the Azure Data Factory copy activity, by subtracting 2 days from the saved watermark. The number of days is a pipeline parameter, per source.

## Why
- It is the simplest design that is correct.
- Bronze stays an exact record of what the source sent and when.
- At the size of this project the repeated data is small. In a hand exercise with 1,000 trades a day, a 2-day lookback re-read 2,203 rows that were already loaded, and a plain watermark missed 4 late rows.

## Consequences
- Bronze contains repeated rows (the same `trade_id` and `trade_version`). Nothing reads Bronze directly. Silver is the first clean layer.
- Row counts in Bronze do not match the source. Compare **distinct keys** instead.
- Silver must always remove repeats and keep the highest valid version of each trade.

## Revisit when
The repeated data becomes large. As a rough guide, the wasted volume per day is `lookback days x daily volume of that table`. At a very large scale (for example terabytes per day), switch to Option 2 for the tables that need a lookback, narrow the window to hours, and prune to recent partitions. Reconciliation against the control totals stays in place either way.
