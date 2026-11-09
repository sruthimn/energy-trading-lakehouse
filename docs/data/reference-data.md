# Reference data

Reference data is the small set of tables that describes the business. It changes slowly, unlike trades, which arrive all day. Everything here is fictional.

Think of it as the **address book** that the trades refer to. A trade says "book BK-UKPWR-01, commodity GB_PWR_BL, counterparty CP-00012". These tables say what those codes mean.

## Commodities (7 rows)

What can be traded.

| Column | Meaning | Example |
|---|---|---|
| `commodity_code` | Short code used in trades | `GB_PWR_BL` |
| `commodity_name` | Readable name | GB Power Baseload |
| `commodity_group` | POWER, GAS, CRUDE or EMISSIONS | POWER |
| `standard_unit` | The unit every volume is converted to in Silver | MWh |
| `native_units` | Units the trading system may send, separated by `|` | `MW|MWh` |
| `quote_currency` | Normal currency for the price | GBP |

**Why `native_units` matters.** A power trade may arrive in megawatts (a rate) or megawatt-hours (an amount). Silver has to convert them to the standard unit, otherwise totals are wrong. This is defect D06.

## Books (12 rows)

A book is a portfolio of trades. Each belongs to a trading desk.

| Column | Meaning | Example |
|---|---|---|
| `book_id` | Unique id: `BK-<desk>-<number>` | `BK-UKPWR-01` |
| `book_name` | Readable name | GB Power Book 1 |
| `desk_code` | The desk that owns the book | UKPWR |
| `trader_group` | The group of traders | TG-POWER |
| `is_active` | Whether the book is open | True |
| `effective_from` | When this version became valid | 2024-01-01 |

Desks: UKPWR (GB power), UKGAS (UK gas), EUGAS (EU gas), CRUDE (oil) and CARB (carbon).

Later, books are moved between desks. The pipeline must keep that history (an SCD Type 2 dimension).

## Counterparties (40 rows by default)

The companies we trade with.

| Column | Meaning | Example |
|---|---|---|
| `counterparty_id` | Unique id, never changes | `CP-00001` |
| `counterparty_name` | Fictional company name | Aldermere Utilities Ltd |
| `country_of_risk` | Country code | GB |
| `credit_rating` | Credit grade, from AA (safest) to BB+ | BBB+ |
| `credit_limit_gbp` | The most we are willing to be exposed to | 80,000,000 |
| `is_active` | Whether we still trade with them | True |
| `effective_from` | When this version became valid | 2024-01-01 |

Later in the simulation, one counterparty is downgraded and one is deleted. Those changes come through the change log (issue #12) and exercise CDC and SCD Type 2.

## Reproducible

The same seed always gives exactly the same data (the default seed is 42). That is what lets the tests prove the pipeline gets the right answer.

## Try it (optional)

Once this change is merged:

```bash
python -c "from lakehouse.generator.reference import generate_reference as g; print(g().counterparties.head())"
```
