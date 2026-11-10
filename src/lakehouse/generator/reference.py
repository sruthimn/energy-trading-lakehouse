"""Reference data: commodities, books and counterparties.

Everything is fictional. The same seed always gives the same data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

# Commodities
# standard_unit is what the Silver layer converts to. native_units are the units a trade can use.
COMMODITIES = [
    # code, name, group, standard_unit, native_units, quote_currency
    ("GB_PWR_BL", "GB Power Baseload", "POWER", "MWh", "MW|MWh", "GBP"),
    ("GB_PWR_PK", "GB Power Peak", "POWER", "MWh", "MW|MWh", "GBP"),
    ("NBP_GAS", "NBP Gas", "GAS", "therm", "therm|MWh", "GBP"),
    ("TTF_GAS", "TTF Gas", "GAS", "therm", "therm|MWh", "EUR"),
    ("BRENT_FUT", "Brent Crude Futures", "CRUDE", "bbl", "bbl|m3", "USD"),
    ("WTI_FUT", "WTI Crude Futures", "CRUDE", "bbl", "bbl|m3", "USD"),
    ("UKA_EMS", "UKA Emissions", "EMISSIONS", "tCO2e", "tCO2e", "GBP"),
]

# Books (portfolios owned by trading desks)
# desk_code, book id prefix, how many books, trader group
DESKS = [
    ("UKPWR", "GB Power", 3, "TG-POWER"),
    ("UKGAS", "UK Gas", 3, "TG-GAS"),
    ("EUGAS", "EU Gas", 2, "TG-GAS"),
    ("CRUDE", "Crude Oil", 3, "TG-OIL"),
    ("CARB", "Carbon", 1, "TG-CARBON"),
]

# Counterparties
# Invented words, so no real company is named.
NAME_STARTS = [
    "Aldermere",
    "Brightwater",
    "Corvane",
    "Dunmoor",
    "Eskerby",
    "Fenhallow",
    "Garrowby",
    "Halvern",
    "Ironvale",
    "Jorvane",
    "Kelmoor",
    "Lormont",
    "Marrowdale",
    "Northcote",
    "Oakhaven",
    "Pellmoor",
    "Quillhurst",
    "Ravenmoor",
    "Stonebrook",
    "Thornvale",
    "Ulverby",
    "Valemoor",
    "Westerling",
    "Yarrowby",
    "Zennock",
    "Ashgrove",
    "Birchwell",
    "Calderby",
    "Dovemoor",
    "Elmstead",
    "Foxhallow",
    "Greywater",
    "Hartwell",
    "Islemoor",
    "Juniper Cross",
    "Kirkvale",
    "Longmere",
    "Mossgate",
    "Nettlebrook",
    "Orrwell",
]
# Names for counterparties onboarded later, kept apart so the first 40 never change.
EXTRA_NAME_STARTS = [
    "Penhallow",
    "Rookwood",
    "Silverdale",
    "Tarnmoor",
    "Umberfield",
    "Vexhall",
    "Wyndmere",
    "Yewbrook",
    "Alderwick",
    "Briarcliff",
]
NAME_SECTORS = [
    "Energy Trading",
    "Utilities",
    "Refining",
    "Carbon Markets",
    "Power Generation",
    "Gas Supply",
    "Commodities",
]
# country code, legal suffix, how likely a counterparty is based there
COUNTRIES = [
    ("GB", "Ltd", 0.40),
    ("DE", "AG", 0.15),
    ("NL", "BV", 0.12),
    ("NO", "AS", 0.10),
    ("US", "Inc", 0.12),
    ("FR", "SA", 0.11),
]
# Credit ratings from safest to riskiest, with a typical credit limit in GBP.
RATINGS = [
    ("AA", 200_000_000),
    ("A+", 150_000_000),
    ("A", 120_000_000),
    ("A-", 100_000_000),
    ("BBB+", 80_000_000),
    ("BBB", 60_000_000),
    ("BBB-", 40_000_000),
    ("BB+", 20_000_000),
]

DEFAULT_SEED = 42
DEFAULT_COUNTERPARTIES = 40
# The date the reference data is first valid from.
INITIAL_EFFECTIVE_DATE = date(2024, 1, 1)


@dataclass(frozen=True)
class ReferenceData:
    """The three reference tables, as pandas tables."""

    commodities: pd.DataFrame
    books: pd.DataFrame
    counterparties: pd.DataFrame


def generate_commodities() -> pd.DataFrame:
    """The fixed list of tradable commodities."""
    return pd.DataFrame(
        COMMODITIES,
        columns=[
            "commodity_code",
            "commodity_name",
            "commodity_group",
            "standard_unit",
            "native_units",
            "quote_currency",
        ],
    )


def generate_books() -> pd.DataFrame:
    """Books: for example BK-UKPWR-01, BK-UKPWR-02. Each belongs to one desk."""
    rows = []
    for desk_code, desk_name, count, trader_group in DESKS:
        for number in range(1, count + 1):
            rows.append(
                {
                    "book_id": f"BK-{desk_code}-{number:02d}",
                    "book_name": f"{desk_name} Book {number}",
                    "desk_code": desk_code,
                    "trader_group": trader_group,
                    "is_active": True,
                    "effective_from": INITIAL_EFFECTIVE_DATE,
                }
            )
    return pd.DataFrame(rows)


def generate_counterparties(seed: int = DEFAULT_SEED, count: int = DEFAULT_COUNTERPARTIES):
    """Fictional companies with a country, a credit rating and a credit limit.

    The ids run CP-00001, CP-00002 and so on, and never change.
    """
    if count > len(NAME_STARTS):
        raise ValueError(f"At most {len(NAME_STARTS)} counterparties are supported")

    rng = random.Random(seed)
    starts = rng.sample(NAME_STARTS, count)  # sample() never repeats a name
    weights = [weight for _, _, weight in COUNTRIES]

    rows = []
    for index, start in enumerate(starts, start=1):
        country, suffix, _ = rng.choices(COUNTRIES, weights=weights, k=1)[0]
        sector = rng.choice(NAME_SECTORS)
        rating, base_limit = rng.choice(RATINGS)
        # Vary the limit a little around the typical value for the rating.
        limit = int(base_limit * rng.uniform(0.75, 1.25) // 1_000_000 * 1_000_000)
        rows.append(
            {
                "counterparty_id": f"CP-{index:05d}",
                "counterparty_name": f"{start} {sector} {suffix}",
                "country_of_risk": country,
                "credit_rating": rating,
                "credit_limit_gbp": limit,
                "is_active": True,
                "effective_from": INITIAL_EFFECTIVE_DATE,
            }
        )
    return pd.DataFrame(rows)


def generate_reference(
    seed: int = DEFAULT_SEED, counterparties: int = DEFAULT_COUNTERPARTIES
) -> ReferenceData:
    """Create all three reference tables."""
    return ReferenceData(
        commodities=generate_commodities(),
        books=generate_books(),
        counterparties=generate_counterparties(seed, counterparties),
    )


def write_reference(data: ReferenceData, out_dir: str | Path) -> list[Path]:
    """Write each table as a CSV file and return the file paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in ("commodities", "books", "counterparties"):
        path = out / f"{name}.csv"
        getattr(data, name).to_csv(path, index=False)
        paths.append(path)
    return paths
