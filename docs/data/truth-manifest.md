# The truth manifest, defects and control totals

Real source systems are messy, and your pipeline has to cope. To prove that it does, the source team spoils a few rows **on purpose** and writes down exactly which ones. That list is the **truth manifest**. Tests compare your pipeline's results with it.

> **Rule:** the pipeline must never read the manifest, `sim_truth`, `sim_state` or `sim_deleted_trades`. They are the answer sheet. Only tests may read them.

## Where things are

| What | Where | Who may read it |
|---|---|---|
| The spoiled data | `trades` table in `etrm.db` | The pipeline |
| The control totals | `<source folder>/control_totals/date=YYYY-MM-DD/control_totals.csv` | The pipeline (this is a finance extract) |
| The truth manifest | `<source folder>/_truth/defects.json` | Tests only |

Write or refresh the manifest at any time:

```bash
python -m lakehouse.generator.cli manifest --dir data/source
```

It is also written automatically after every `advance`.

## The defects injected in this step

| ID | What happens | Rate (default) | What the pipeline must do |
|---|---|---|---|
| **D04** | One mandatory field is empty (`book_id`, `commodity_code`, `delivery_start`, `volume` or `unit`) | about 0.05% of rows | Send the row to the dead letter queue (DLQ) with a reason. Do not fail the job |
| **D05** | `delivery_end` is before `delivery_start` | about 0.02% of rows | Same: DLQ |
| **D06** | Volumes in different units | About a quarter of trades | Convert to the standard unit (MWh, therm, bbl, tCO2e) |
| **D07** | Clock changes: 29 Mar 2026 has 46 half-hour periods, 25 Oct 2026 has 50 | Every power trade in MW whose period contains one | Convert to UTC before measuring the length of a period |
| **D14** | A trade points to a counterparty that does not exist (`CP-9xxxx`) | about 0.02% of new trades | Do not lose the trade. The relationship check must flag it |
| **D17** | Five old trades are physically **deleted** from the source on 2 Apr 2026 | 5 trades | A watermark cannot see this. The daily reconciliation to the control totals must catch it |

Defects from earlier steps (amendments D01, cancellations D02, late rows D03, the downgrade D08 and the counterparty deletion D16) are in the manifest too.

Each spoiled row is only spoiled in the database. A later amendment of the same trade is a clean row.

## The manifest

`defects.json` has three parts:

- **`meta`**: the seed, the trades per day, and how many days were simulated.
- **`defects`**: for each defect, the count, and for the row-level ones the exact `trade_id` and `trade_version` (plus the column, or the fake counterparty id).
- **`expected`**: the correct results, worked out from the data with the rules below. Your Silver and Gold results should match these.

### The rules the truth uses

1. A row is **invalid** if a mandatory field is empty (D04) or the delivery period ends before it starts (D05). Invalid rows go to the DLQ.
2. Among the **valid** rows, keep the **highest version** of each trade.
3. If that version is `CANCELLED`, the trade is **not active**.
4. Volumes are converted to the standard unit, **counting clock changes**.

Note rule 2: if version 2 of a trade is invalid and version 1 is valid, the truth keeps version 1. That is the same order of steps as the Silver code in the design: split valid and invalid first, then keep the latest.

### Two views of the truth

| View | What it is | Use it to test |
|---|---|---|
| `source_now` | What the source holds today | The control totals, and any pipeline that re-reads everything |
| `pipeline_view` | `source_now` plus the trades that were hard deleted | A watermark pipeline that loaded the trades **before** they were deleted |

The difference between the two is exactly the 5 trades of D17. A pipeline that only uses a watermark ends up with `pipeline_view`, and the control totals show `source_now`. That gap is how you find the problem.

## Control totals

Each day, the source writes an end-of-day file, like the one a trading system sends to finance:

| Column | Meaning |
|---|---|
| `business_date` | The day the file was written |
| `book_id` | The book |
| `trade_count` | Active trades in the book, **cumulative** up to that day |
| `total_volume_std` | Their total volume in the standard unit |

"Active" follows the rules above: valid rows only, latest version, not cancelled.

You will reconcile Gold against these every day. Any difference above a tolerance blocks the publish (design acceptance criterion 7).

## Example: why D07 needs care

A power trade for March 2026, delivered in MW:

| Calculation | Hours | 10 MW becomes |
|---|---|---|
| Subtract the clock times (wrong) | 744 | 7,440 MWh |
| Convert to UTC first, then subtract (right) | 743 | 7,430 MWh |

March has one hour less than it looks, because the clocks go forward on 29 March. In the sample run, 21,668 power trades were affected. If Silver measures the period using local clock times, every one of them is wrong by one hour of volume, and the control totals will not match.

## Real numbers from a run (seed 42, 20,000 trades per day, 18 days)

| Check | Result |
|---|---|
| Rows with an empty mandatory field | 209, exactly as injected |
| Rows with the end before the start | 87, exactly as injected |
| Rejected rows the pipeline should find | 296 (209 plus 87) |
| Orphan counterparties | 76 |
| Hard deleted trades | 5, on 2 Apr |
| Active trades now (`source_now`) | 353,845 |
| Active trades a watermark pipeline holds (`pipeline_view`) | 353,850 |

## Try it

In a Codespace after merging:

```bash
python -m lakehouse.generator.cli init --dir data/source --trades-per-day 2000
python -m lakehouse.generator.cli advance --dir data/source --days 18
cat data/source/_truth/defects.json | head -60
head data/source/control_totals/date=2026-04-08/control_totals.csv
```
