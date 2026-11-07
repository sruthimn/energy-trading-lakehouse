"""Tests for the simulated source database and its command line."""

import sqlite3
from datetime import date

import pytest

from lakehouse.generator.cli import main
from lakehouse.generator.source_db import DB_NAME, SourceSystem

MONDAY = date(2026, 3, 16)


def make(tmp_path, trades_per_day=400, **kwargs):
    return SourceSystem.create(tmp_path / "src", trades_per_day=trades_per_day, **kwargs)


def query(system, sql, params=()):
    with sqlite3.connect(system.db_path) as con:
        return con.execute(sql, params).fetchall()


def all_trade_rows(system):
    return query(system, "SELECT * FROM trades ORDER BY trade_id, trade_version")


# --- creating it -----------------------------------------------------------


def test_create_loads_the_reference_tables(tmp_path):
    system = make(tmp_path)
    assert query(system, "SELECT COUNT(*) FROM books")[0][0] == 12
    assert query(system, "SELECT COUNT(*) FROM commodities")[0][0] == 7
    assert query(system, "SELECT COUNT(*) FROM counterparties")[0][0] == 40


def test_a_new_system_has_no_trades_and_starts_on_the_chosen_day(tmp_path):
    system = make(tmp_path)
    assert query(system, "SELECT COUNT(*) FROM trades")[0][0] == 0
    assert system.next_business_date == MONDAY


def test_cannot_create_twice_in_the_same_folder(tmp_path):
    make(tmp_path)
    with pytest.raises(FileExistsError):
        make(tmp_path)


def test_cannot_start_on_a_weekend(tmp_path):
    with pytest.raises(ValueError):
        make(tmp_path, start_date=date(2026, 3, 21))


def test_opening_a_missing_system_fails_clearly(tmp_path):
    with pytest.raises(FileNotFoundError):
        SourceSystem(tmp_path / "nothing-here")


# --- advancing one day at a time -------------------------------------------


def test_advance_adds_one_days_trades_and_moves_to_the_next_day(tmp_path):
    system = make(tmp_path)
    (result,) = system.advance()
    assert result.business_date == MONDAY
    assert result.new_trades == 400
    assert query(system, "SELECT COUNT(*) FROM trades")[0][0] == result.rows
    assert system.next_business_date == date(2026, 3, 17)


def test_the_weekend_is_skipped(tmp_path):
    system = make(tmp_path, trades_per_day=20)
    days = [r.business_date for r in system.advance(6)]
    assert days[4] == date(2026, 3, 20)  # Friday
    assert days[5] == date(2026, 3, 23)  # the next Monday
    assert system.next_business_date == date(2026, 3, 24)


def test_stored_values_have_the_expected_format(tmp_path):
    system = make(tmp_path, trades_per_day=50)
    system.advance()
    row = query(system, "SELECT last_modified, delivery_start, trade_date FROM trades LIMIT 1")[0]
    assert len(row[0]) == 19 and row[0][10] == " "  # 2026-03-16 14:05:31
    assert len(row[1]) == 19
    assert row[2] == "2026-03-16"


def test_every_trade_row_has_all_values(tmp_path):
    system = make(tmp_path, trades_per_day=100)
    system.advance(3)
    nulls = query(
        system, "SELECT COUNT(*) FROM trades WHERE trade_id IS NULL OR last_modified IS NULL"
    )
    assert nulls[0][0] == 0


# --- carrying on later (the important part) -----------------------------------


def test_closing_and_reopening_gives_the_same_result_as_running_straight_through(tmp_path):
    straight = SourceSystem.create(tmp_path / "a", trades_per_day=300)
    straight.advance(6)

    stopped = SourceSystem.create(tmp_path / "b", trades_per_day=300)
    stopped.advance(2)
    reopened = SourceSystem(tmp_path / "b")  # a new program run, like tomorrow
    reopened.advance(4)

    assert all_trade_rows(straight) == all_trade_rows(reopened)
    assert straight.next_business_date == reopened.next_business_date


def test_the_same_settings_give_identical_databases(tmp_path):
    a = SourceSystem.create(tmp_path / "a", trades_per_day=200)
    b = SourceSystem.create(tmp_path / "b", trades_per_day=200)
    a.advance(4)
    b.advance(4)
    assert all_trade_rows(a) == all_trade_rows(b)


def test_amendments_arrive_on_later_days_as_new_versions(tmp_path):
    system = make(tmp_path, trades_per_day=500)
    system.advance(8)
    versions = query(system, "SELECT MAX(trade_version) FROM trades")[0][0]
    assert versions >= 2
    amended = query(system, "SELECT COUNT(*) FROM trades WHERE status = 'AMENDED'")[0][0]
    assert amended > 0


# --- late rows (defect D03) ------------------------------------------------------


def test_the_first_day_has_no_late_rows(tmp_path):
    system = make(tmp_path, trades_per_day=2000, late_rate=0.5)
    assert system.advance()[0].late_rows == 0


def test_late_rows_are_recorded_in_the_truth_table(tmp_path):
    system = make(tmp_path, trades_per_day=2000, late_rate=0.01)
    results = system.advance(5)
    total_late = sum(r.late_rows for r in results)
    assert total_late > 0
    recorded = query(system, "SELECT COUNT(*) FROM sim_truth WHERE kind = 'LATE_ROW'")[0][0]
    assert recorded == total_late


def test_a_late_row_is_older_than_rows_already_in_the_database(tmp_path):
    system = make(tmp_path, trades_per_day=2000, late_rate=0.01)
    system.advance()
    newest_before = query(system, "SELECT MAX(last_modified) FROM trades")[0][0]
    result = system.advance()[0]
    assert result.late_rows > 0
    for trade_id, version in result.late_keys:
        (last_modified,) = query(
            system,
            "SELECT last_modified FROM trades WHERE trade_id = ? AND trade_version = ?",
            (trade_id, version),
        )[0]
        assert last_modified < newest_before


def test_a_watermark_on_last_modified_misses_the_late_rows(tmp_path):
    """The lesson of defect D03, shown in the simplest possible way."""
    system = make(tmp_path, trades_per_day=2000, late_rate=0.01)
    system.advance()
    watermark = query(system, "SELECT MAX(last_modified) FROM trades")[0][0]

    result = system.advance()[0]
    seen = query(system, "SELECT COUNT(*) FROM trades WHERE last_modified > ?", (watermark,))[0][0]
    todays_rows = result.rows

    assert result.late_rows > 0
    assert todays_rows - seen == result.late_rows  # exactly the late rows are missed


# --- the command line ----------------------------------------------------------


def test_command_line_init_advance_status(tmp_path, capsys):
    folder = str(tmp_path / "cli")
    assert main(["init", "--dir", folder, "--trades-per-day", "50"]) == 0
    assert (tmp_path / "cli" / DB_NAME).exists()

    assert main(["advance", "--dir", folder, "--days", "2"]) == 0
    assert main(["status", "--dir", folder]) == 0
    output = capsys.readouterr().out
    assert "2026-03-16" in output and "2026-03-17" in output
    assert "next_business_date: 2026-03-18" in output
