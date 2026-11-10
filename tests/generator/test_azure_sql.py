"""Tests for copying the source database into Azure SQL.

SQLite stands in for Azure SQL here, so these tests check the sync logic, not the T-SQL.
"""

import sqlite3
from datetime import date

from lakehouse.generator.azure_sql import sync
from lakehouse.generator.source_db import SCHEMA, SourceSystem

TABLES = [
    "trades",
    "commodities",
    "books",
    "counterparties",
    "cdc_counterparties",
    "cdc_books",
]


def make(tmp_path, **kwargs):
    return SourceSystem.create(tmp_path / "src", trades_per_day=200, **kwargs)


def target_database(db_path):
    """An empty SQLite database with the same tables as the source."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    with sqlite3.connect(db_path) as source:
        # The reference tables are not in SCHEMA, so copy their definitions.
        for (ddl,) in source.execute(
            "SELECT sql FROM sqlite_master WHERE name IN ('commodities', 'books', 'counterparties')"
        ):
            con.execute(ddl)
    return con


def rows(con, table):
    return sorted(con.execute(f"SELECT * FROM {table}").fetchall())


def assert_same(source, target):
    for table in TABLES:
        assert rows(source, table) == rows(target, table), table


def test_first_sync_copies_every_table(tmp_path):
    system = make(tmp_path)
    system.advance(3)
    target = target_database(system.db_path)
    with sqlite3.connect(system.db_path) as source:
        result = sync(source, target, prefix="")
        assert result["trades added"] == source.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert_same(source, target)


def test_a_second_sync_with_no_new_day_changes_nothing(tmp_path):
    system = make(tmp_path)
    system.advance(2)
    target = target_database(system.db_path)
    with sqlite3.connect(system.db_path) as source:
        sync(source, target, prefix="")
        result = sync(source, target, prefix="")
    assert result["trades added"] == 0
    assert result["trades removed"] == 0
    assert result["cdc_counterparties rows added"] == 0


def test_a_new_day_adds_only_the_new_rows(tmp_path):
    system = make(tmp_path)
    system.advance(2)
    target = target_database(system.db_path)
    with sqlite3.connect(system.db_path) as source:
        sync(source, target, prefix="")
        before = target.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    system.advance(1)
    with sqlite3.connect(system.db_path) as source:
        result = sync(source, target, prefix="")
        after = source.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert result["trades added"] == after - before
        assert_same(source, target)


def test_late_rows_are_added_even_though_their_last_modified_is_old(tmp_path):
    system = make(tmp_path)
    system.advance(1)
    target = target_database(system.db_path)
    with sqlite3.connect(system.db_path) as source:
        sync(source, target, prefix="")
    results = system.advance(4)
    late = sum(day.late_rows for day in results)
    assert late > 0
    with sqlite3.connect(system.db_path) as source:
        sync(source, target, prefix="")
        assert_same(source, target)


def test_trades_deleted_at_the_source_are_removed_from_the_target(tmp_path):
    system = make(tmp_path, hard_delete_day=date(2026, 3, 25), hard_delete_count=3)
    system.advance(7)
    target = target_database(system.db_path)
    with sqlite3.connect(system.db_path) as source:
        sync(source, target, prefix="")
    system.advance(2)
    with sqlite3.connect(system.db_path) as source:
        deleted = source.execute(
            "SELECT COUNT(DISTINCT trade_id) FROM sim_deleted_trades"
        ).fetchone()
        assert deleted[0] == 3
        result = sync(source, target, prefix="")
        assert result["trades removed"] >= 3
        assert_same(source, target)


def test_reference_changes_and_the_change_log_follow_the_source(tmp_path):
    system = make(tmp_path)
    system.advance(4)
    target = target_database(system.db_path)
    with sqlite3.connect(system.db_path) as source:
        sync(source, target, prefix="")
    system.advance(5)
    with sqlite3.connect(system.db_path) as source:
        result = sync(source, target, prefix="")
        assert result["cdc_counterparties rows added"] + result["cdc_books rows added"] > 0
        assert_same(source, target)
