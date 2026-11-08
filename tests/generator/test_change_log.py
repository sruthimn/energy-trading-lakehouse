"""Tests for the reference data change log (CDC) and the changes behind it."""

import sqlite3
from datetime import date

import pytest

from lakehouse.generator.master_data import (
    DEFAULT_BOOK_REMAP_DAY,
    DEFAULT_DELETE_DAY,
    DEFAULT_DOWNGRADE_DAY,
    DEFAULT_ONBOARD_DAY,
    RATING_ORDER,
    TABLE_COLUMNS,
    TABLE_KEY,
)
from lakehouse.generator.source_db import SourceSystem
from lakehouse.generator.trades import business_days

START = date(2026, 3, 16)


def advance_until(system, last_day):
    """Advance the system up to and including `last_day`."""
    return system.advance(len(business_days(system.next_business_date, last_day)))


def query(system, sql, params=()):
    with sqlite3.connect(system.db_path) as con:
        return con.execute(sql, params).fetchall()


def replay(system, table):
    """Rebuild a table by applying its change log in order. This is what CDC is for."""
    key = TABLE_KEY[table]
    columns = TABLE_COLUMNS[table]
    log = query(
        system,
        f"SELECT operation, {', '.join(columns)} FROM cdc_{table} ORDER BY lsn",
    )
    state = {}
    for operation, *values in log:
        row = dict(zip(columns, values, strict=True))
        if operation == "D":
            state.pop(row[key], None)
        else:
            state[row[key]] = row
    return state


def current(system, table):
    columns = TABLE_COLUMNS[table]
    rows = query(system, f"SELECT {', '.join(columns)} FROM {table}")
    return {row[0]: dict(zip(columns, row, strict=True)) for row in rows}


@pytest.fixture(scope="module")
def system(tmp_path_factory):
    """A source system simulated through all the scripted events."""
    folder = tmp_path_factory.mktemp("cdc") / "src"
    source = SourceSystem.create(folder, trades_per_day=300)
    advance_until(source, date(2026, 4, 10))
    return source


# --- the log at the start --------------------------------------------------------


def test_the_log_starts_with_one_insert_for_every_reference_row(tmp_path):
    source = SourceSystem.create(tmp_path / "s")
    counterparties = query(source, "SELECT operation, lsn FROM cdc_counterparties ORDER BY lsn")
    books = query(source, "SELECT operation, lsn FROM cdc_books ORDER BY lsn")
    assert len(counterparties) == 40 and len(books) == 12
    assert {op for op, _ in counterparties + books} == {"I"}
    lsns = [lsn for _, lsn in counterparties + books]
    assert sorted(lsns) == list(range(1, 53))


# --- the log is a faithful record -------------------------------------------------


def test_replaying_the_counterparty_log_rebuilds_the_table(system):
    assert replay(system, "counterparties") == current(system, "counterparties")


def test_replaying_the_book_log_rebuilds_the_table(system):
    assert replay(system, "books") == current(system, "books")


def test_sequence_numbers_only_go_up_across_both_logs(system):
    lsns = [
        lsn
        for (lsn,) in query(
            system,
            "SELECT lsn FROM cdc_counterparties UNION ALL SELECT lsn FROM cdc_books",
        )
    ]
    assert len(lsns) == len(set(lsns))  # no number is used twice
    ordered = sorted(lsns)
    assert ordered == list(range(1, len(lsns) + 1))  # and there are no gaps


def test_commit_times_never_go_backwards_as_the_sequence_goes_up(system):
    rows = query(
        system,
        "SELECT lsn, commit_time FROM cdc_counterparties "
        "UNION ALL SELECT lsn, commit_time FROM cdc_books ORDER BY lsn",
    )
    times = [commit_time for _, commit_time in rows]
    assert times == sorted(times)


# --- scripted events ----------------------------------------------------------------


def test_nothing_scripted_happens_before_its_day(tmp_path):
    source = SourceSystem.create(tmp_path / "s", trades_per_day=50)
    advance_until(source, date(2026, 3, 18))
    kinds = {kind for (kind,) in query(source, "SELECT kind FROM sim_truth")}
    assert not kinds & {"DOWNGRADE", "DELETE", "ONBOARD", "BOOK_REMAP"}


def test_the_downgrade_lowers_the_rating_and_cuts_the_limit(system):
    ((day, counterparty_id),) = query(
        system, "SELECT business_date, detail FROM sim_truth WHERE kind = 'DOWNGRADE'"
    )
    assert day == DEFAULT_DOWNGRADE_DAY.isoformat()
    before, after = query(
        system,
        "SELECT credit_rating, credit_limit_gbp FROM cdc_counterparties "
        "WHERE counterparty_id = ? AND operation IN ('I', 'U') ORDER BY lsn LIMIT 2",
        (counterparty_id,),
    )
    assert RATING_ORDER.index(after[0]) > RATING_ORDER.index(before[0])
    assert after[1] < before[1]


def test_a_deleted_counterparty_is_gone_from_the_table_but_not_from_the_log(system):
    ((day, counterparty_id),) = query(
        system, "SELECT business_date, detail FROM sim_truth WHERE kind = 'DELETE'"
    )
    assert day == DEFAULT_DELETE_DAY.isoformat()
    assert (
        query(system, "SELECT 1 FROM counterparties WHERE counterparty_id = ?", (counterparty_id,))
        == []
    )
    operations = [
        op
        for (op,) in query(
            system,
            "SELECT operation FROM cdc_counterparties WHERE counterparty_id = ? ORDER BY lsn",
            (counterparty_id,),
        )
    ]
    assert operations[0] == "I" and operations[-1] == "D"


def test_a_delete_keeps_the_last_known_values(system):
    ((counterparty_id,),) = query(system, "SELECT detail FROM sim_truth WHERE kind = 'DELETE'")
    last_update, delete = query(
        system,
        "SELECT credit_rating, counterparty_name FROM cdc_counterparties "
        "WHERE counterparty_id = ? ORDER BY lsn DESC LIMIT 2",
        (counterparty_id,),
    )[::-1]
    assert delete[1] == last_update[1]  # the name is still there in the delete record


def test_a_deleted_counterparty_gets_no_new_trades_afterwards(system):
    ((counterparty_id,),) = query(system, "SELECT detail FROM sim_truth WHERE kind = 'DELETE'")
    newer = query(
        system,
        "SELECT COUNT(*) FROM trades WHERE counterparty_id = ? "
        "AND trade_version = 1 AND trade_date > ?",
        (counterparty_id, DEFAULT_DELETE_DAY.isoformat()),
    )
    assert newer[0][0] == 0


def test_older_trades_still_point_to_the_deleted_counterparty(system):
    ((counterparty_id,),) = query(system, "SELECT detail FROM sim_truth WHERE kind = 'DELETE'")
    (count,) = query(
        system, "SELECT COUNT(*) FROM trades WHERE counterparty_id = ?", (counterparty_id,)
    )[0]
    assert count > 0  # history is kept, so the pipeline must keep the old version too


def test_a_new_counterparty_is_onboarded_and_then_used(system):
    ((day, counterparty_id),) = query(
        system, "SELECT business_date, detail FROM sim_truth WHERE kind = 'ONBOARD'"
    )
    assert day == DEFAULT_ONBOARD_DAY.isoformat()
    assert counterparty_id == "CP-00041"
    used = query(
        system, "SELECT COUNT(*) FROM trades WHERE counterparty_id = ?", (counterparty_id,)
    )
    assert used[0][0] > 0


def test_a_book_is_moved_to_another_desk(system):
    ((day, book_id),) = query(
        system, "SELECT business_date, detail FROM sim_truth WHERE kind = 'BOOK_REMAP'"
    )
    assert day == DEFAULT_BOOK_REMAP_DAY.isoformat()
    desks = [
        desk
        for (desk,) in query(
            system, "SELECT desk_code FROM cdc_books WHERE book_id = ? ORDER BY lsn", (book_id,)
        )
    ]
    assert desks == ["UKGAS", "EUGAS"]


def test_each_scripted_event_happens_exactly_once(system):
    for kind in ("DOWNGRADE", "DELETE", "ONBOARD", "BOOK_REMAP"):
        (count,) = query(system, "SELECT COUNT(*) FROM sim_truth WHERE kind = ?", (kind,))[0]
        assert count == 1, kind


def test_some_small_random_changes_also_happen(system):
    (count,) = query(
        system,
        "SELECT COUNT(*) FROM sim_truth WHERE kind IN ('LIMIT_CHANGE', 'RATING_CHANGE')",
    )[0]
    assert count > 0


# --- stopping and restarting -----------------------------------------------------------


def test_stopping_and_restarting_gives_the_same_change_log(tmp_path):
    straight = SourceSystem.create(tmp_path / "a", trades_per_day=100)
    advance_until(straight, date(2026, 4, 7))

    stopped = SourceSystem.create(tmp_path / "b", trades_per_day=100)
    advance_until(stopped, date(2026, 3, 25))  # before the onboarding and the deletion
    reopened = SourceSystem(tmp_path / "b")
    advance_until(reopened, date(2026, 4, 7))

    for table in ("cdc_counterparties", "cdc_books"):
        sql = f"SELECT * FROM {table} ORDER BY lsn"
        assert query(straight, sql) == query(reopened, sql)
