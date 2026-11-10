"""Copy the local source database (SQLite) into the Azure SQL database.

It can be run again after every simulated day:
- new trade rows are added, and trades deleted at the source are removed (defect D17)
- the reference tables are replaced, because they only hold the current state
- change log rows (CDC) are appended
"""

from __future__ import annotations

import os
import sqlite3
import time

from lakehouse.generator.master_data import TABLE_COLUMNS
from lakehouse.generator.trades import TRADE_COLUMNS

COMMODITY_COLUMNS = [
    "commodity_code",
    "commodity_name",
    "commodity_group",
    "standard_unit",
    "native_units",
    "quote_currency",
]
REFERENCE_COLUMNS = {
    "commodities": COMMODITY_COLUMNS,
    "books": TABLE_COLUMNS["books"],
    "counterparties": TABLE_COLUMNS["counterparties"],
}
LOG_TABLES = ("counterparties", "books")
BATCH_SIZE = 5000

# Table definitions for Azure SQL (T-SQL). Each one is created only if it is missing.
CREATE_STATEMENTS = [
    """
    IF OBJECT_ID('dbo.trades', 'U') IS NULL
    CREATE TABLE dbo.trades (
        trade_id        NVARCHAR(32)  NOT NULL,
        trade_version   INT           NOT NULL,
        book_id         NVARCHAR(32)  NULL,
        commodity_code  NVARCHAR(32)  NULL,
        buy_sell        NVARCHAR(8)   NOT NULL,
        volume          FLOAT         NULL,
        unit            NVARCHAR(16)  NULL,
        price           FLOAT         NOT NULL,
        currency        NVARCHAR(8)   NOT NULL,
        delivery_start  DATETIME2(0)  NULL,
        delivery_end    DATETIME2(0)  NOT NULL,
        counterparty_id NVARCHAR(16)  NOT NULL,
        trader_id       NVARCHAR(16)  NOT NULL,
        status          NVARCHAR(16)  NOT NULL,
        trade_date      DATE          NOT NULL,
        last_modified   DATETIME2(0)  NOT NULL,
        CONSTRAINT pk_trades PRIMARY KEY (trade_id, trade_version)
    )
    """,
    """
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_trades_last_modified')
    CREATE INDEX idx_trades_last_modified ON dbo.trades (last_modified)
    """,
    """
    IF OBJECT_ID('dbo.commodities', 'U') IS NULL
    CREATE TABLE dbo.commodities (
        commodity_code  NVARCHAR(32) NOT NULL PRIMARY KEY,
        commodity_name  NVARCHAR(64) NOT NULL,
        commodity_group NVARCHAR(16) NOT NULL,
        standard_unit   NVARCHAR(16) NOT NULL,
        native_units    NVARCHAR(32) NOT NULL,
        quote_currency  NVARCHAR(8)  NOT NULL
    )
    """,
    """
    IF OBJECT_ID('dbo.books', 'U') IS NULL
    CREATE TABLE dbo.books (
        book_id        NVARCHAR(32) NOT NULL PRIMARY KEY,
        book_name      NVARCHAR(64) NOT NULL,
        desk_code      NVARCHAR(16) NOT NULL,
        trader_group   NVARCHAR(16) NOT NULL,
        is_active      INT          NOT NULL,
        effective_from DATE         NOT NULL
    )
    """,
    """
    IF OBJECT_ID('dbo.counterparties', 'U') IS NULL
    CREATE TABLE dbo.counterparties (
        counterparty_id   NVARCHAR(16)  NOT NULL PRIMARY KEY,
        counterparty_name NVARCHAR(128) NOT NULL,
        country_of_risk   NVARCHAR(4)   NOT NULL,
        credit_rating     NVARCHAR(8)   NOT NULL,
        credit_limit_gbp  BIGINT        NOT NULL,
        is_active         INT           NOT NULL,
        effective_from    DATE          NOT NULL
    )
    """,
    """
    IF OBJECT_ID('dbo.cdc_counterparties', 'U') IS NULL
    CREATE TABLE dbo.cdc_counterparties (
        lsn               BIGINT        NOT NULL PRIMARY KEY,
        commit_time       DATETIME2(0)  NOT NULL,
        operation         CHAR(1)       NOT NULL CHECK (operation IN ('I', 'U', 'D')),
        counterparty_id   NVARCHAR(16)  NOT NULL,
        counterparty_name NVARCHAR(128) NOT NULL,
        country_of_risk   NVARCHAR(4)   NOT NULL,
        credit_rating     NVARCHAR(8)   NOT NULL,
        credit_limit_gbp  BIGINT        NOT NULL,
        is_active         INT           NOT NULL,
        effective_from    DATE          NOT NULL
    )
    """,
    """
    IF OBJECT_ID('dbo.cdc_books', 'U') IS NULL
    CREATE TABLE dbo.cdc_books (
        lsn            BIGINT       NOT NULL PRIMARY KEY,
        commit_time    DATETIME2(0) NOT NULL,
        operation      CHAR(1)      NOT NULL CHECK (operation IN ('I', 'U', 'D')),
        book_id        NVARCHAR(32) NOT NULL,
        book_name      NVARCHAR(64) NOT NULL,
        desk_code      NVARCHAR(16) NOT NULL,
        trader_group   NVARCHAR(16) NOT NULL,
        is_active      INT          NOT NULL,
        effective_from DATE         NOT NULL
    )
    """,
]


def connect_from_environment():
    """Open a connection using the AZSQL_* environment variables.

    The password is never passed on the command line, so it stays out of the shell history.
    """
    import pyodbc

    server = os.environ.get("AZSQL_SERVER")
    password = os.environ.get("AZSQL_PASSWORD")
    if not server or not password:
        raise SystemExit(
            "Set AZSQL_SERVER and AZSQL_PASSWORD first (see docs/data/azure-sql-load.md)."
        )
    database = os.environ.get("AZSQL_DATABASE", "etrm")
    user = os.environ.get("AZSQL_USER", "energy_admin")
    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER=tcp:{server},1433;DATABASE={database};UID={user};PWD={password};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60"
    )
    # A paused serverless database needs a short time to start, so the first try can fail.
    for attempt in range(1, 5):
        try:
            return pyodbc.connect(connection_string)
        except pyodbc.Error:
            if attempt == 4:
                raise
            print(f"Database not ready (try {attempt} of 4). Waiting 30 seconds.")
            time.sleep(30)


def create_tables(target) -> None:
    """Create the source tables in Azure SQL if they do not exist yet."""
    cursor = target.cursor()
    for statement in CREATE_STATEMENTS:
        cursor.execute(statement)
    target.commit()


def sync(source: sqlite3.Connection, target, prefix: str = "dbo.") -> dict[str, int]:
    """Bring the target up to date with the source and return what changed.

    `prefix` is the schema in front of table names. Tests pass "" to use SQLite as the target.
    """
    result = _sync_trades(source, target, prefix)
    for table, columns in REFERENCE_COLUMNS.items():
        result[f"{table} rows"] = _replace_table(source, target, prefix, table, columns)
    for table in LOG_TABLES:
        columns = ["lsn", "commit_time", "operation", *TABLE_COLUMNS[table]]
        result[f"cdc_{table} rows added"] = _append_log(source, target, prefix, table, columns)
    target.commit()
    return result


def _sync_trades(source, target, prefix: str) -> dict[str, int]:
    # Compare keys, not last_modified: late rows have an old last_modified.
    remote_keys = {
        (row[0], row[1])
        for row in target.cursor().execute(f"SELECT trade_id, trade_version FROM {prefix}trades")
    }
    columns = ", ".join(TRADE_COLUMNS)
    local_keys = set()
    new_rows = []
    for row in source.execute(f"SELECT {columns} FROM trades ORDER BY trade_id, trade_version"):
        key = (row[0], row[1])
        local_keys.add(key)
        if key not in remote_keys:
            new_rows.append(tuple(row))

    placeholders = ", ".join("?" * len(TRADE_COLUMNS))
    _insert_in_batches(
        target, f"INSERT INTO {prefix}trades ({columns}) VALUES ({placeholders})", new_rows
    )

    deleted = sorted(remote_keys - local_keys)
    cursor = target.cursor()
    for start in range(0, len(deleted), BATCH_SIZE):
        cursor.executemany(
            f"DELETE FROM {prefix}trades WHERE trade_id = ? AND trade_version = ?",
            deleted[start : start + BATCH_SIZE],
        )
    return {"trades added": len(new_rows), "trades removed": len(deleted)}


def _replace_table(source, target, prefix: str, table: str, columns: list[str]) -> int:
    names = ", ".join(columns)
    rows = [tuple(r) for r in source.execute(f"SELECT {names} FROM {table}")]
    target.cursor().execute(f"DELETE FROM {prefix}{table}")
    placeholders = ", ".join("?" * len(columns))
    _insert_in_batches(
        target, f"INSERT INTO {prefix}{table} ({names}) VALUES ({placeholders})", rows
    )
    return len(rows)


def _append_log(source, target, prefix: str, table: str, columns: list[str]) -> int:
    cursor = target.cursor()
    last_lsn = cursor.execute(f"SELECT COALESCE(MAX(lsn), 0) FROM {prefix}cdc_{table}").fetchone()[
        0
    ]
    names = ", ".join(columns)
    rows = [
        tuple(r)
        for r in source.execute(
            f"SELECT {names} FROM cdc_{table} WHERE lsn > ? ORDER BY lsn", (last_lsn,)
        )
    ]
    placeholders = ", ".join("?" * len(columns))
    _insert_in_batches(
        target, f"INSERT INTO {prefix}cdc_{table} ({names}) VALUES ({placeholders})", rows
    )
    return len(rows)


def _insert_in_batches(target, statement: str, rows: list[tuple]) -> None:
    cursor = target.cursor()
    if hasattr(cursor, "fast_executemany"):
        cursor.fast_executemany = True
    for start in range(0, len(rows), BATCH_SIZE):
        cursor.executemany(statement, rows[start : start + BATCH_SIZE])
