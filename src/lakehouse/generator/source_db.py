"""The simulated trading system database (etrm.db, SQLite).

It moves forward one business day at a time and keeps its progress in the database, so it can
be stopped and continued later. The tables are described in docs/data/source-database.md.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from lakehouse.generator.defects import (
    DEFAULT_BAD_RANGE_RATE,
    DEFAULT_HARD_DELETE_COUNT,
    DEFAULT_HARD_DELETE_DAY,
    DEFAULT_NULL_RATE,
    DEFAULT_ORPHAN_RATE,
    DefectInjector,
)
from lakehouse.generator.master_data import (
    TABLE_COLUMNS,
    TABLE_KEY,
    Change,
    MasterDataSimulator,
)
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
from lakehouse.generator.truth import book_totals, load_trades, write_control_totals, write_truth

DB_NAME = "etrm.db"
DEFAULT_START_DATE = date(2026, 3, 16)  # a Monday
DEFAULT_TRADES_PER_DAY = 1000

SCHEMA = """
CREATE TABLE trades (
    trade_id        TEXT    NOT NULL,
    trade_version   INTEGER NOT NULL,
    book_id         TEXT,
    commodity_code  TEXT,
    buy_sell        TEXT    NOT NULL,
    volume          REAL,
    unit            TEXT,
    price           REAL    NOT NULL,
    currency        TEXT    NOT NULL,
    delivery_start  TEXT,
    delivery_end    TEXT    NOT NULL,
    counterparty_id TEXT    NOT NULL,
    trader_id       TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,
    last_modified   TEXT    NOT NULL,
    PRIMARY KEY (trade_id, trade_version)
);
CREATE INDEX idx_trades_last_modified ON trades (last_modified);

-- Copies of rows that were physically deleted from trades (defect D17).
CREATE TABLE sim_deleted_trades (
    trade_id        TEXT,
    trade_version   INTEGER,
    book_id         TEXT,
    commodity_code  TEXT,
    buy_sell        TEXT,
    volume          REAL,
    unit            TEXT,
    price           REAL,
    currency        TEXT,
    delivery_start  TEXT,
    delivery_end    TEXT,
    counterparty_id TEXT,
    trader_id       TEXT,
    status          TEXT,
    trade_date      TEXT,
    last_modified   TEXT,
    deleted_on      TEXT
);

CREATE TABLE sim_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE sim_truth (
    business_date TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    trade_id      TEXT,
    trade_version INTEGER,
    detail        TEXT
);

-- The change logs. Each row says: at this moment (commit_time), this change
-- (operation: I insert, U update, D delete) produced this row. For a delete,
-- the row is what it looked like just before it was deleted.
-- lsn is a log sequence number: it only ever goes up, across both logs.
CREATE TABLE cdc_counterparties (
    lsn               INTEGER PRIMARY KEY,
    commit_time       TEXT    NOT NULL,
    operation         TEXT    NOT NULL CHECK (operation IN ('I', 'U', 'D')),
    counterparty_id   TEXT    NOT NULL,
    counterparty_name TEXT    NOT NULL,
    country_of_risk   TEXT    NOT NULL,
    credit_rating     TEXT    NOT NULL,
    credit_limit_gbp  INTEGER NOT NULL,
    is_active         INTEGER NOT NULL,
    effective_from    TEXT    NOT NULL
);
CREATE TABLE cdc_books (
    lsn            INTEGER PRIMARY KEY,
    commit_time    TEXT    NOT NULL,
    operation      TEXT    NOT NULL CHECK (operation IN ('I', 'U', 'D')),
    book_id        TEXT    NOT NULL,
    book_name      TEXT    NOT NULL,
    desk_code      TEXT    NOT NULL,
    trader_group   TEXT    NOT NULL,
    is_active      INTEGER NOT NULL,
    effective_from TEXT    NOT NULL
);
"""

# The reference tables were loaded into the system long before the simulation
# starts. The change log begins with one insert for each of those rows.
INITIAL_LOAD_TIME = datetime(2024, 1, 1, 6, 0, 0)

# Trades that are safe to hard delete: old, valid, active, with a real counterparty
# and only one version.
CANDIDATES_FOR_DELETE = """
SELECT trade_id FROM trades
WHERE trade_date <= ?
  AND status != 'CANCELLED'
  AND counterparty_id NOT LIKE 'CP-9%'
  AND book_id IS NOT NULL AND commodity_code IS NOT NULL AND volume IS NOT NULL
  AND unit IS NOT NULL AND delivery_start IS NOT NULL AND delivery_end > delivery_start
  AND trade_id IN (SELECT trade_id FROM trades GROUP BY trade_id HAVING COUNT(*) = 1)
ORDER BY trade_id
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
    master_changes: int
    defects_injected: int
    trades_deleted: int


class SourceSystem:
    """The simulated trading system. Create it once, then advance it day by day."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.db_path = self.directory / DB_NAME
        if not self.db_path.exists():
            raise FileNotFoundError(f"No source system found in {self.directory}. Create it first.")
        self._load()

    @classmethod
    def create(
        cls,
        directory: str | Path,
        seed: int = DEFAULT_SEED,
        trades_per_day: int = DEFAULT_TRADES_PER_DAY,
        start_date: date = DEFAULT_START_DATE,
        counterparties: int = DEFAULT_COUNTERPARTIES,
        late_rate: float = LATE_ROW_RATE,
        null_rate: float = DEFAULT_NULL_RATE,
        bad_range_rate: float = DEFAULT_BAD_RANGE_RATE,
        orphan_rate: float = DEFAULT_ORPHAN_RATE,
        hard_delete_day: date = DEFAULT_HARD_DELETE_DAY,
        hard_delete_count: int = DEFAULT_HARD_DELETE_COUNT,
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
        master = MasterDataSimulator(seed)
        master.next_counterparty_number = counterparties + 1
        injector = _make_injector(
            seed,
            {
                "null_rate": null_rate,
                "bad_range_rate": bad_range_rate,
                "orphan_rate": orphan_rate,
                "hard_delete_day": hard_delete_day.isoformat(),
                "hard_delete_count": hard_delete_count,
            },
        )
        config = {
            "seed": seed,
            "trades_per_day": trades_per_day,
            "counterparties": counterparties,
            "late_rate": late_rate,
            "null_rate": null_rate,
            "bad_range_rate": bad_range_rate,
            "orphan_rate": orphan_rate,
            "hard_delete_day": hard_delete_day.isoformat(),
            "hard_delete_count": hard_delete_count,
            "next_day": start_date.isoformat(),
        }
        with sqlite3.connect(db_path) as con:
            con.executescript(SCHEMA)
            _write_reference(con, reference)
            next_lsn = _write_initial_change_log(con)
            _save_state(
                con,
                config,
                simulator.get_state(),
                _master_state(master, next_lsn),
                injector.get_state(),
            )
        return cls(directory)

    @property
    def next_business_date(self) -> date:
        """The business day that the next call to advance() will simulate."""
        return self._next_day

    def advance(self, days: int = 1) -> list[DayResult]:
        """Simulate the next business day (or several) and save the result."""
        return [self._advance_one_day() for _ in range(days)]

    def write_truth_manifest(self) -> Path:
        """Write the truth manifest to <directory>/_truth/defects.json."""
        return write_truth(self.directory, self.db_path)

    def status(self) -> dict:
        """Where the simulation is, as a small summary."""
        with sqlite3.connect(self.db_path) as con:
            rows, trades = con.execute(
                "SELECT COUNT(*), COUNT(DISTINCT trade_id) FROM trades"
            ).fetchone()
            newest = con.execute("SELECT MAX(last_modified) FROM trades").fetchone()[0]
            changes = con.execute(
                "SELECT (SELECT COUNT(*) FROM cdc_counterparties)"
                " + (SELECT COUNT(*) FROM cdc_books)"
            ).fetchone()[0]
        return {
            "next_business_date": self._next_day.isoformat(),
            "trade_rows": rows,
            "distinct_trades": trades,
            "newest_last_modified": newest,
            "change_log_rows": changes,
        }

    def _load(self) -> None:
        """Read the saved progress and rebuild the simulator from it."""
        with sqlite3.connect(self.db_path) as con:
            config = json.loads(
                con.execute("SELECT value FROM sim_state WHERE key='config'").fetchone()[0]
            )
            state = json.loads(
                con.execute("SELECT value FROM sim_state WHERE key='state'").fetchone()[0]
            )
            master_state = json.loads(
                con.execute("SELECT value FROM sim_state WHERE key='master'").fetchone()[0]
            )
            defects_state = json.loads(
                con.execute("SELECT value FROM sim_state WHERE key='defects'").fetchone()[0]
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
        self._group_of = dict(
            zip(
                reference.commodities["commodity_code"],
                reference.commodities["commodity_group"],
                strict=True,
            )
        )
        self._defects = _make_injector(config["seed"], config)
        self._defects.set_state(defects_state)
        self._master = MasterDataSimulator(config["seed"])
        self._master.set_state(master_state["simulator"])
        self._next_lsn = master_state["next_lsn"]

    def _advance_one_day(self) -> DayResult:
        day = self._next_day
        before = self._simulator.stats
        counts_before = (before.new_trades, before.amendments, before.cancellations)
        try:
            clean_frame = self._simulator.simulate_day(day)
            frame, injections = self._defects.spoil(clean_frame)
            after = self._simulator.stats
            late_keys = tuple(self._simulator.late_keys)
            next_day = add_business_days(day, 1)
            config = {**self._config, "next_day": next_day.isoformat()}
            # One transaction: the new rows and the saved progress succeed or fail together.
            with sqlite3.connect(self.db_path) as con:
                con.executemany(INSERT_TRADE, _to_sql_rows(frame))
                con.executemany(
                    "INSERT INTO sim_truth VALUES (?, 'LATE_ROW', ?, ?, NULL)",
                    [(day.isoformat(), trade_id, version) for trade_id, version in late_keys],
                )
                con.executemany(
                    "INSERT INTO sim_truth VALUES (?, ?, ?, ?, ?)",
                    [
                        (day.isoformat(), i.kind, i.trade_id, i.trade_version, i.detail or None)
                        for i in injections
                    ],
                )
                changes = self._master.changes_for_day(
                    day, _read_table(con, "counterparties"), _read_table(con, "books")
                )
                next_lsn = self._next_lsn
                for change in changes:
                    _apply_change(con, change, next_lsn)
                    con.execute(
                        "INSERT INTO sim_truth VALUES (?, ?, NULL, NULL, ?)",
                        (day.isoformat(), change.kind, change.row[TABLE_KEY[change.table]]),
                    )
                    self._tell_trade_simulator(change)
                    next_lsn += 1
                deleted_ids = self._hard_delete(con, day)
                totals = book_totals(load_trades(con), self._group_of, day)
                _save_state(
                    con,
                    config,
                    self._simulator.get_state(),
                    _master_state(self._master, next_lsn),
                    self._defects.get_state(),
                )
            # The database is saved. Now write the day's control totals file.
            write_control_totals(self.directory, day, totals)
        except Exception:
            self._load()  # forget the half-finished day and go back to the saved progress
            raise

        self._config = config
        self._next_day = next_day
        self._next_lsn = next_lsn
        return DayResult(
            business_date=day,
            rows=len(frame),
            new_trades=after.new_trades - counts_before[0],
            amendments=after.amendments - counts_before[1],
            cancellations=after.cancellations - counts_before[2],
            late_rows=len(late_keys),
            late_keys=late_keys,
            master_changes=len(changes),
            defects_injected=len(injections),
            trades_deleted=len(deleted_ids),
        )

    def _hard_delete(self, con: sqlite3.Connection, day: date) -> list[str]:
        """Physically delete a few old trades (defect D17).

        A watermark load cannot see a deleted row. The rows are copied to sim_deleted_trades
        first, so tests know what was deleted.
        """
        if not self._defects.is_hard_delete_day(day):
            return []
        cutoff = (day - timedelta(days=3)).isoformat()
        rows = con.execute(CANDIDATES_FOR_DELETE, (cutoff,)).fetchall()
        candidates = [r[0] for r in rows if not self._simulator.has_pending_changes(r[0])]
        chosen = self._defects.pick_trades_to_delete(candidates)
        for trade_id in chosen:
            versions = con.execute(
                "SELECT trade_version FROM trades WHERE trade_id = ?", (trade_id,)
            ).fetchall()
            con.execute(
                "INSERT INTO sim_deleted_trades SELECT *, ? FROM trades WHERE trade_id = ?",
                (day.isoformat(), trade_id),
            )
            con.execute("DELETE FROM trades WHERE trade_id = ?", (trade_id,))
            con.executemany(
                "INSERT INTO sim_truth VALUES (?, 'HARD_DELETE', ?, ?, NULL)",
                [(day.isoformat(), trade_id, version) for (version,) in versions],
            )
        return chosen

    def _tell_trade_simulator(self, change: Change) -> None:
        """New trades must not use a deleted counterparty, and may use a new one."""
        if change.table != "counterparties":
            return
        counterparty_id = change.row["counterparty_id"]
        if change.operation == "D":
            self._simulator.retire_counterparty(counterparty_id)
        elif change.operation == "I":
            self._simulator.add_counterparty(counterparty_id)


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


def _make_injector(seed: int, settings: dict) -> DefectInjector:
    return DefectInjector(
        seed,
        null_rate=settings["null_rate"],
        bad_range_rate=settings["bad_range_rate"],
        orphan_rate=settings["orphan_rate"],
        hard_delete_day=date.fromisoformat(settings["hard_delete_day"]),
        hard_delete_count=settings["hard_delete_count"],
    )


def _save_state(
    con: sqlite3.Connection,
    config: dict,
    state: dict,
    master_state: dict,
    defects_state: dict,
) -> None:
    for key, value in (
        ("config", config),
        ("state", state),
        ("master", master_state),
        ("defects", defects_state),
    ):
        con.execute("INSERT OR REPLACE INTO sim_state VALUES (?, ?)", (key, json.dumps(value)))


def _master_state(master: MasterDataSimulator, next_lsn: int) -> dict:
    return {"simulator": master.get_state(), "next_lsn": next_lsn}


def _read_table(con: sqlite3.Connection, table: str) -> list[dict]:
    """All current rows of a reference table, as plain dictionaries."""
    columns = TABLE_COLUMNS[table]
    cursor = con.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {TABLE_KEY[table]}")
    return [dict(zip(columns, row, strict=True)) for row in cursor]


def _write_initial_change_log(con: sqlite3.Connection) -> int:
    """One insert per existing reference row. Returns the next log sequence number."""
    lsn = 1
    for table in ("counterparties", "books"):
        for row in _read_table(con, table):
            commit_time = INITIAL_LOAD_TIME + timedelta(seconds=lsn)
            _write_log_row(con, table, "I", row, commit_time, lsn)
            lsn += 1
    return lsn


def _write_log_row(
    con: sqlite3.Connection,
    table: str,
    operation: str,
    row: dict,
    commit_time: datetime,
    lsn: int,
) -> None:
    columns = TABLE_COLUMNS[table]
    names = ", ".join(["lsn", "commit_time", "operation", *columns])
    marks = ", ".join("?" * (len(columns) + 3))
    values = [lsn, commit_time.strftime(TIME_FORMAT), operation, *(row[c] for c in columns)]
    con.execute(f"INSERT INTO cdc_{table} ({names}) VALUES ({marks})", values)


def _apply_change(con: sqlite3.Connection, change: Change, lsn: int) -> None:
    """Change the table, and write the change to its log, in the same transaction."""
    table, row = change.table, change.row
    columns = TABLE_COLUMNS[table]
    key = TABLE_KEY[table]
    if change.operation == "I":
        names = ", ".join(columns)
        marks = ", ".join("?" * len(columns))
        con.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", [row[c] for c in columns])
    elif change.operation == "U":
        others = [c for c in columns if c != key]
        sets = ", ".join(f"{c} = ?" for c in others)
        con.execute(
            f"UPDATE {table} SET {sets} WHERE {key} = ?", [*(row[c] for c in others), row[key]]
        )
    else:
        con.execute(f"DELETE FROM {table} WHERE {key} = ?", [row[key]])
    _write_log_row(con, table, change.operation, row, change.commit_time, lsn)


def _to_sql_rows(frame: pd.DataFrame) -> list[list]:
    """Turn a table of trades into plain rows, with dates written as text."""
    out = frame.copy()
    for column in ("delivery_start", "delivery_end", "last_modified"):
        out[column] = out[column].dt.strftime(TIME_FORMAT)
    out["trade_date"] = out["trade_date"].map(lambda d: d.isoformat())
    out = out.astype(object)
    out = out.where(out.notna(), None)  # a missing value becomes NULL in the database
    return out.values.tolist()
