"""Trades: the busiest table in the trading system.

How a trading system really behaves, and what this module copies
----------------------------------------------------------------
* A trader does a deal. The system writes one row: trade_id, version 1.
* A later day, the deal is amended (a volume or price changes). The system does
  NOT overwrite the row. It writes a NEW row: same trade_id, version 2.
* A deal can also be cancelled. That is one more row, with status CANCELLED.

So the table holds every version of every trade. The pipeline's job is to work
out which version is the latest. That is defects D01 (amendments) and D02
(cancellations) in the design.

Timestamps are written in UK local time with no time zone, as many trading
systems do. Converting them to UTC is the pipeline's job.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd

from lakehouse.generator.reference import ReferenceData

# Conversion factors. The trading system knows the real physics. The Silver
# layer has to use the same factors to put every volume in a standard unit.
THERM_PER_MWH = 34.1214
BBL_PER_M3 = 6.28981

# Which commodities each desk trades.
DESK_COMMODITIES = {
    "UKPWR": ["GB_PWR_BL", "GB_PWR_PK"],
    "UKGAS": ["NBP_GAS"],
    "EUGAS": ["TTF_GAS"],
    "CRUDE": ["BRENT_FUT", "WTI_FUT"],
    "CARB": ["UKA_EMS"],
}


@dataclass(frozen=True)
class Profile:
    """What a typical trade looks like for one commodity."""

    id_prefix: str  # the three letters in the trade id, for example PWR
    volume: tuple[float, float]  # typical volume range, in the main unit
    price: tuple[float, float]  # typical price range, in the quote currency
    delivery_start_hour: int  # power starts at 00:00, the gas day at 05:00


PROFILES = {
    "GB_PWR_BL": Profile("PWR", (5, 100), (55, 110), 0),
    "GB_PWR_PK": Profile("PWR", (5, 60), (65, 130), 7),
    "NBP_GAS": Profile("GAS", (50_000, 500_000), (0.40, 1.50), 5),
    "TTF_GAS": Profile("GAS", (50_000, 400_000), (25, 60), 5),
    "BRENT_FUT": Profile("CRD", (10_000, 1_000_000), (60, 100), 0),
    "WTI_FUT": Profile("CRD", (10_000, 800_000), (55, 95), 0),
    "UKA_EMS": Profile("EMS", (5_000, 200_000), (30, 60), 0),
}

# How the simulation behaves. These are the knobs of the source team.
AMENDMENT_RATE = 0.08  # share of trades amended at least once (defect D01)
MAX_AMENDMENTS = 4  # a trade can be amended up to this many times
CANCELLATION_RATE = 0.02  # share of trades cancelled (defect D02)
MAX_TRADE_NUMBER = 999_999  # trade ids have six digits

TRADE_COLUMNS = [
    "trade_id",
    "trade_version",
    "book_id",
    "commodity_code",
    "buy_sell",
    "volume",
    "unit",
    "price",
    "currency",
    "delivery_start",
    "delivery_end",
    "counterparty_id",
    "trader_id",
    "status",
    "trade_date",
    "last_modified",
]


def is_business_day(day: date) -> bool:
    """Monday to Friday. (UK bank holidays are ignored to keep it simple.)"""
    return day.weekday() < 5


def add_business_days(day: date, count: int) -> date:
    """The date that is `count` business days after `day`."""
    current = day
    while count > 0:
        current += timedelta(days=1)
        if is_business_day(current):
            count -= 1
    return current


def business_days(start: date, end: date) -> list[date]:
    """Every business day from `start` to `end`, both included."""
    days = []
    current = start
    while current <= end:
        if is_business_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def to_standard_volume(
    volume: float,
    unit: str,
    commodity_group: str,
    delivery_start: datetime,
    delivery_end: datetime,
) -> float:
    """What the volume is worth in the standard unit (the truth the pipeline must match).

    * Power in MW is a rate, so it is multiplied by the hours of the delivery
      period to give megawatt-hours.
    * Gas in MWh is converted to therms.
    * Crude in cubic metres is converted to barrels.
    """
    if commodity_group == "POWER":
        if unit == "MW":
            hours = (delivery_end - delivery_start).total_seconds() / 3600
            return volume * hours
        return volume  # already MWh
    if commodity_group == "GAS":
        return volume * THERM_PER_MWH if unit == "MWh" else volume
    if commodity_group == "CRUDE":
        return volume * BBL_PER_M3 if unit == "m3" else volume
    return volume  # emissions: tCO2e only


@dataclass
class SimulationStats:
    """Running counts, used later for the truth manifest."""

    days: int = 0
    new_trades: int = 0
    amendments: int = 0  # extra version rows caused by amendments
    amended_trades: int = 0  # distinct trades that were amended at least once
    cancellations: int = 0
    rows: int = 0


@dataclass
class TradeSimulator:
    """Creates trades day by day, and amends or cancels some of them later.

    Use it like this:

        sim = TradeSimulator(reference, seed=42, trades_per_day=1000)
        for day in business_days(date(2026, 3, 16), date(2026, 4, 10)):
            todays_rows = sim.simulate_day(day)

    Days must be simulated in order, because an amendment on day 5 depends on
    the trade that was created on day 2.
    """

    reference: ReferenceData
    seed: int = 42
    trades_per_day: int = 1000
    stats: SimulationStats = field(default_factory=SimulationStats)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._counter = 0  # the next trade number
        self._latest: dict[str, dict] = {}  # latest version of trades with later actions
        self._schedule: dict[date, list[tuple[str, str]]] = {}  # day -> (trade_id, action)
        self._last_day: date | None = None
        self._commodity_group = dict(
            zip(
                self.reference.commodities["commodity_code"],
                self.reference.commodities["commodity_group"],
                strict=True,
            )
        )
        self._native_units = {
            code: units.split("|")
            for code, units in zip(
                self.reference.commodities["commodity_code"],
                self.reference.commodities["native_units"],
                strict=True,
            )
        }
        self._quote_currency = dict(
            zip(
                self.reference.commodities["commodity_code"],
                self.reference.commodities["quote_currency"],
                strict=True,
            )
        )
        self._books = self.reference.books.to_dict("records")
        self._counterparties = self.reference.counterparties["counterparty_id"].tolist()
        self._traders = [f"TR-{number:04d}" for number in range(5001, 5031)]

    # ------------------------------------------------------------------
    def simulate_day(self, day: date) -> pd.DataFrame:
        """All trade rows written on this business day (new, amended, cancelled)."""
        if not is_business_day(day):
            raise ValueError(f"{day} is not a business day")
        if self._last_day is not None and day <= self._last_day:
            raise ValueError("Days must be simulated in order, each one once")
        self._last_day = day

        rows: list[dict] = []
        for _ in range(self.trades_per_day):
            rows.append(self._new_trade(day))
        rows.extend(self._due_actions(day))

        self.stats.days += 1
        self.stats.rows += len(rows)
        return pd.DataFrame(rows, columns=TRADE_COLUMNS)

    # ------------------------------------------------------------------
    def _new_trade(self, day: date) -> dict:
        rng = self._rng
        self._counter += 1
        if self._counter > MAX_TRADE_NUMBER:
            raise ValueError("Trade ids have six digits. Lower trades_per_day or the days.")

        book = rng.choice(self._books)
        commodity = rng.choice(DESK_COMMODITIES[book["desk_code"]])
        profile = PROFILES[commodity]
        group = self._commodity_group[commodity]

        start, end = self._delivery_period(day, profile)
        unit = self._choose_unit(commodity)
        volume = self._volume(profile, unit, group, start, end)
        quote_currency = self._quote_currency[commodity]

        trade_id = f"TRD-{profile.id_prefix}-{self._counter:06d}"
        row = {
            "trade_id": trade_id,
            "trade_version": 1,
            "book_id": book["book_id"],
            "commodity_code": commodity,
            "buy_sell": rng.choice(["BUY", "SELL"]),
            "volume": volume,
            "unit": unit,
            "price": round(rng.uniform(*profile.price), 4),
            "currency": quote_currency,
            "delivery_start": start,
            "delivery_end": end,
            "counterparty_id": rng.choice(self._counterparties),
            "trader_id": rng.choice(self._traders),
            "status": "CONFIRMED" if rng.random() < 0.85 else "PENDING",
            "trade_date": day,
            "last_modified": self._time_on(day),
        }
        self.stats.new_trades += 1
        self._plan_later_changes(day, row)
        return row

    def _plan_later_changes(self, day: date, row: dict) -> None:
        """Decide now whether this trade will be amended or cancelled later."""
        rng = self._rng
        amend = rng.random() < AMENDMENT_RATE
        cancel = rng.random() < CANCELLATION_RATE
        if not amend and not cancel:
            return

        offset = 0
        if amend:
            for _ in range(rng.randint(1, MAX_AMENDMENTS)):
                offset += rng.randint(1, 4)
                self._schedule.setdefault(add_business_days(day, offset), []).append(
                    (row["trade_id"], "AMEND")
                )
        if cancel:
            offset += rng.randint(1, 4)  # always after the last amendment
            self._schedule.setdefault(add_business_days(day, offset), []).append(
                (row["trade_id"], "CANCEL")
            )
        self._latest[row["trade_id"]] = row

    def _due_actions(self, day: date) -> list[dict]:
        """The amendments and cancellations that are due today."""
        rng = self._rng
        rows = []
        for trade_id, action in self._schedule.pop(day, []):
            latest = self._latest[trade_id]
            new = dict(latest)
            new["trade_version"] = latest["trade_version"] + 1
            new["last_modified"] = self._time_on(day)
            if action == "AMEND":
                new["status"] = "AMENDED"
                if rng.random() < 0.6:  # most amendments change the volume
                    factor = rng.uniform(0.7, 1.3)
                    new["volume"] = round(latest["volume"] * factor, 2)
                else:
                    new["price"] = round(latest["price"] * rng.uniform(0.95, 1.05), 4)
                self.stats.amendments += 1
                if latest["trade_version"] == 1:
                    self.stats.amended_trades += 1
            else:
                new["status"] = "CANCELLED"
                self.stats.cancellations += 1
            rows.append(new)
            self._latest[trade_id] = new
        return rows

    # ------------------------------------------------------------------
    def _delivery_period(self, day: date, profile: Profile) -> tuple[datetime, datetime]:
        """A delivery period starting 1 to 12 months ahead, lasting 1 or 3 months."""
        months_ahead = self._rng.randint(1, 12)
        length = self._rng.choice([1, 1, 3])
        year = day.year + (day.month - 1 + months_ahead) // 12
        month = (day.month - 1 + months_ahead) % 12 + 1
        start = datetime(year, month, 1, profile.delivery_start_hour)
        end_month_index = (month - 1) + length
        end = datetime(
            year + end_month_index // 12,
            end_month_index % 12 + 1,
            1,
            profile.delivery_start_hour,
        )
        return start, end

    def _choose_unit(self, commodity: str) -> str:
        """Most trades use the first native unit. About 25% use another one."""
        units = self._native_units[commodity]
        if len(units) == 1 or self._rng.random() < 0.75:
            return units[0]
        return self._rng.choice(units[1:])

    def _volume(self, profile: Profile, unit: str, group: str, start, end) -> float:
        """A volume in the chosen unit, based on a typical amount in the main unit."""
        base = self._rng.uniform(*profile.volume)
        if group == "POWER" and unit == "MWh":
            hours = (end - start).total_seconds() / 3600
            base = base * hours  # a megawatt rate over the period gives megawatt-hours
        elif group == "GAS" and unit == "MWh":
            base = base / THERM_PER_MWH
        elif group == "CRUDE" and unit == "m3":
            base = base / BBL_PER_M3
        return round(base, 2)

    def _time_on(self, day: date) -> datetime:
        """A random working-hours time on the given day."""
        seconds = self._rng.randint(8 * 3600, 17 * 3600 + 1800)
        return datetime(day.year, day.month, day.day) + timedelta(seconds=seconds)
