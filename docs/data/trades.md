# Trades

The trades table is the busiest table in the (fictional) trading system. Every deal is recorded here.

## The most important idea: versions

A trading system never overwrites a trade. It writes a **new row** each time something changes. This is a real example from the generator (seed 42):

| trade_id | trade_version | volume | unit | price | status | last_modified |
|---|---|---|---|---|---|---|
| TRD-CRD-000102 | 1 | 65,929.13 | m3 | 87.1559 | CONFIRMED | 2026-03-16 14:05 |
| TRD-CRD-000102 | 2 | 48,835.91 | m3 | 87.1559 | AMENDED | 2026-03-19 11:44 |
| TRD-CRD-000102 | 3 | 57,560.65 | m3 | 87.1559 | AMENDED | 2026-03-24 15:19 |
| TRD-CRD-000102 | 4 | 61,696.48 | m3 | 87.1559 | AMENDED | 2026-03-26 17:20 |
| TRD-CRD-000102 | 5 | 56,870.73 | m3 | 87.1559 | AMENDED | 2026-03-31 10:39 |

One deal, five rows. If you added all the volumes you would count the same deal five times. The pipeline must keep **only version 5**. This is defect **D01**.

A trade can also be **cancelled**. That is one more row with status `CANCELLED`, and nothing is written for the trade after that. This is defect **D02**.

## Columns

| Column | Meaning | Example |
|---|---|---|
| `trade_id` | The deal. Same id for all versions. Pattern `TRD-XXX-000000` | `TRD-PWR-000123` |
| `trade_version` | 1 for the first row, then 2, 3 and so on | 3 |
| `book_id` | The portfolio the deal belongs to | `BK-UKPWR-01` |
| `commodity_code` | What was traded | `GB_PWR_BL` |
| `buy_sell` | BUY or SELL | BUY |
| `volume` | How much, **in the unit given** | 50 |
| `unit` | MW, MWh, therm, bbl, m3 or tCO2e | MW |
| `price` | Price per unit in the currency | 78.40 |
| `currency` | GBP, EUR or USD | GBP |
| `delivery_start`, `delivery_end` | When the energy is delivered. UK local time, no time zone | 2026-05-01 00:00 |
| `counterparty_id` | The company on the other side | `CP-00012` |
| `trader_id` | The trader. Personal data, so it is pseudonymised later | `TR-5021` |
| `status` | PENDING, CONFIRMED, AMENDED or CANCELLED | CONFIRMED |
| `trade_date` | The business day of the original deal | 2026-03-16 |
| `last_modified` | When this row was written. The watermark column | 2026-03-16 14:05:31 |

## Why units are tricky (defect D06)

The same deal can be expressed in different units, so volumes cannot be added up directly.

| Commodity | Standard unit | Other units that arrive | How to convert |
|---|---|---|---|
| Power | MWh | **MW** | MW is a rate. Multiply by the hours in the delivery period |
| Gas | therm | **MWh** | 1 MWh = 34.1214 therms |
| Crude | bbl | **m3** | 1 m3 = 6.28981 barrels |
| Emissions | tCO2e | none | none |

The generator contains a function, `to_standard_volume`, that holds the correct answer. Tests use it to check your Silver layer later.

## How the generator behaves

- Business days only (Monday to Friday). UK bank holidays are ignored.
- Each desk trades only its own commodities (the power desk never trades crude).
- Gas deliveries start at 05:00, because the gas day runs from 05:00 to 05:00.
- About **8% of trades are amended** one to four times, and about **2% are cancelled**. In a short simulation, a few of these changes fall after the last day, so the observed shares are slightly lower. At full size, over 20 days: 7.0% amended and 1.7% cancelled.
- About **0.5% of new trades arrive a day late** (defect D03): their `trade_date` and `last_modified` say yesterday, but the row only reaches the database today. At full size over 20 days that is 1,911 rows. See `docs/data/source-database.md` for why this matters.
- The same seed always gives the same data.
- The simulator counts what it creates (new trades, amendments, cancellations). These counts will go into the truth manifest (issue #13) so tests can prove the pipeline finds every one.

## Try it (optional, in your Codespace after merging)

```bash
python - <<'EOF'
from datetime import date
from lakehouse.generator.reference import generate_reference
from lakehouse.generator.trades import TradeSimulator, business_days

sim = TradeSimulator(generate_reference(), seed=42, trades_per_day=1000)
rows = [sim.simulate_day(day) for day in business_days(date(2026, 3, 16), date(2026, 3, 27))]
print(sim.stats)
EOF
```
