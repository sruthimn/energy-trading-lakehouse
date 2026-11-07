"""The simulated trading system database.

This is the "source system" that the pipeline reads from. It is a small SQLite
file called etrm.db (ETRM is the usual name for a trading system).

It moves forward **one business day at a time**. Each day it adds the trade rows
that the simulator produced, exactly as a real system adds rows while traders
work. Run it again tomorrow and it carries on from where it stopped, even if
the program was closed in between.

Tables the pipeline may read
----------------------------
trades          every version of every trade (the busiest table)
books           reference data (full load)
commodities     reference data (full load)
counterparties  reference data (change data capture is added in a later step)

Tables the pipeline must NOT read
---------------------------------
sim_state       where the simulator saves its progress
sim_truth       a private record of what was injected, used by tests
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from lakehouse.generator.reference import (
    DEFAULT_COUNTERPARTIES,
    DEFAULT_SEED,
    ReferenceData,
    generate_reference,
)
from lakehouse.generator.trades import (
    LATE_ROW_RATE,
    TRADE_COLUMNS,
    TradeSimulator,
    add_business_days,
    is_business_day,
)

DB_NAME = "etrm.db"
DEFAULT_START_DATE = date(2026, 3, 16)  # a Monday
DEFAULT_TRADES_PER_DAY = 1000

SCHEMA = """
CREATE TABLE trades (
    trade_id        TEXT    NOT NULL,
    trade_version   INTEGER NOT NULL,
    book_id         TEXT    NOT NULL,
    commodity_code  TEXT    NOT NULL,
    buy_sell        TEXT    NOT NULL,
    volume          REAL    NOT NULL,
    unit            TEXT    NOT NULL,
    price           REAL    NOT NULL,
    currency        TEXT    NOT NULL,
    delivery_start  TEXT    NOT NULL,
    delivery_end    TEXT    NOT NULL,
    counterparty_id TEXT    NOT NULL,
    trader_id       TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,
    last_modified   TEXT    NOT NULL,
    PRIMARY KEY (trade_id, trade_version)
);
CREATE INDEX idx_trades_last_modified ON trades (last_modified);

CREATE TABLE sim_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE sim_truth (
    business_date TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    trade_id      TEXT,
    trade_version INTEGER
);
"""

_COLUMN_LIST = ", ".join(TRADE_COLUMNS)
_PLACEHOLDERS = ", ".join("?" * len(TRADE_COLUMNS))
INSERT_TRADE = f"INSERT INTO trades ({_COLUMN_LIST}) VALUES ({_PLACEHOLDERS})"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class DayResult:
    """What happened on one simulated day."""

    business_date: date
    rows: int
    new_trades: int
    amendments: int
    cancellations: int
    late_rows: int
    late_keys: tuple[tuple[str, int], ...]


class SourceSystem:
    """The simulated trading system. Create it once, then advance it day by day."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.db_path = self.directory / DB_NAME
        if not self.db_path.exists():
            raise FileNotFoundError(f"No source system found in {self.directory}. Create it first.")
        self._load()

    # ------------------------------------------------------------------
    @classmethod
    def create(
        cls,
        directory: str | Path,
        seed: int = DEFAULT_SEED,
        trades_per_day: int = DEFAULT_TRADES_PER_DAY,
        start_date: date = DEFAULT_START_DATE,
        counterparties: int = DEFAULT_COUNTERPARTIES,
        late_rate: float = LATE_ROW_RATE,
    ) -> SourceSystem:
        """Create a new, empty source system with its reference data loaded."""
        directory = Path(directory)
        db_path = directory / DB_NAME
        if db_path.exists():
            raise FileExistsError(f"A source system already exists in {directory}")
        if not is_business_day(start_date):
            raise ValueError(f"{start_date} is not a business day")
        directory.mkdir(parents=True, exist_ok=True)

        reference = generate_reference(seed, counterparties)
        simulator = TradeSimulator(
            reference, seed=seed, trades_per_day=trades_per_day, late_rate=late_rate
        )
        config = {
            "seed": seed,
            "trades_per_day": trades_per_day,
            "counterparties": counterparties,
            "late_rate": late_rate,
            "next_day": start_date.isoformat(),
        }
        with sqlite3.connect(db_path) as con:
            con.executescript(SCHEMA)
            _write_reference(con, reference)
            _save_state(con, config, simulator.get_state())
        return cls(directory)

    # ------------------------------------------------------------------
    @property
    def next_business_date(self) -> date:
        """The business day that the next call to advance() will simulate."""
        return self._next_day

    def advance(self, days: int = 1) -> list[DayResult]:
        """Simulate the next business day (or several) and save the result."""
        return [self._advance_one_day() for _ in range(days)]

    def status(self) -> dict:
        """A short summary, for people."""
        with sqlite3.connect(self.db_path) as con:
            rows, trades = con.execute(
                "SELECT COUNT(*), COUNT(DISTINCT trade_id) FROM trades"
            ).fetchone()
            newest = con.execute("SELECT MAX(last_modified) FROM trades").fetchone()[0]
        return {
            "next_business_date": self._next_day.isoformat(),
            "trade_rows": rows,
            "distinct_trades": trades,
            "newest_last_modified": newest,
        }

    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Read the saved progress and rebuild the simulator from it."""
        with sqlite3.connect(self.db_path) as con:
            config = json.loads(
                con.execute("SELECT value FROM sim_state WHERE key='config'").fetchone()[0]
            )
            state = json.loads(
                con.execute("SELECT value FROM sim_state WHERE key='state'").fetchone()[0]
            )
        self._config = config
        self._next_day = date.fromisoformat(config["next_day"])
        reference = generate_reference(config["seed"], config["counterparties"])
        self._simulator = TradeSimulator(
            reference,
            seed=config["seed"],
            trades_per_day=config["trades_per_day"],
            late_rate=config["late_rate"],
        )
        self._simulator.set_state(state)

    def _advance_one_day(self) -> DayResult:
        day = self._next_day
        before = self._simulator.stats
        counts_before = (before.new_trades, before.amendments, before.cancellations)
        try:
            frame = self._simulator.simulate_day(day)
            after = self._simulator.stats
            late_keys = tuple(self._simulator.late_keys)
            next_day = add_business_days(day, 1)
            config = {**self._config, "next_day": next_day.isoformat()}
            # One transaction: the new rows and the saved progress succeed or fail together.
            with sqlite3.connect(self.db_path) as con:
                con.executemany(INSERT_TRADE, _to_sql_rows(frame))
                con.executemany(
                    "INSERT INTO sim_truth VALUES (?, 'LATE_ROW', ?, ?)",
                    [(day.isoformat(), trade_id, version) for trade_id, version in late_keys],
                )
                _save_state(con, config, self._simulator.get_state())
        except Exception:
            self._load()  # forget the half-finished day and go back to the saved progress
            raise

        self._config = config
        self._next_day = next_day
        return DayResult(
            business_date=day,
            rows=len(frame),
            new_trades=after.new_trades - counts_before[0],
            amendments=after.amendments - counts_before[1],
            cancellations=after.cancellations - counts_before[2],
            late_rows=len(late_keys),
            late_keys=late_keys,
        )


# ----------------------------------------------------------------------
def _write_reference(con: sqlite3.Connection, reference: ReferenceData) -> None:
    """Load the reference tables into the database."""
    for name in ("commodities", "books", "counterparties"):
        table = getattr(reference, name).copy()
        for column in table.columns:
            if table[column].dtype == bool:
                table[column] = table[column].astype(int)
            elif column == "effective_from":
                table[column] = table[column].astype(str)
        table.to_sql(name, con, index=False, if_exists="replace")


def _save_state(con: sqlite3.Connection, config: dict, state: dict) -> None:
    con.execute("INSERT OR REPLACE INTO sim_state VALUES ('config', ?)", (json.dumps(config),))
    con.execute("INSERT OR REPLACE INTO sim_state VALUES ('state', ?)", (json.dumps(state),))


def _to_sql_rows(frame: pd.DataFrame) -> list[list]:
    """Turn a table of trades into plain rows, with dates written as text."""
    out = frame.copy()
    for column in ("delivery_start", "delivery_end", "last_modified"):
        out[column] = out[column].dt.strftime(TIME_FORMAT)
    out["trade_date"] = out["trade_date"].map(lambda d: d.isoformat())
    return out.astype(object).values.tolist()
