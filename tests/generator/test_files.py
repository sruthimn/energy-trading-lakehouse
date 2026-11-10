"""Tests for the daily CSV and JSON files."""

import csv
import json
import sqlite3

from lakehouse.generator.files import (
    COUNTERPARTY_FEED,
    TRADE_FEED,
    export_files,
)
from lakehouse.generator.source_db import SourceSystem
from lakehouse.generator.trades import TRADE_COLUMNS


def make(tmp_path, name="src", **kwargs):
    return SourceSystem.create(tmp_path / name, trades_per_day=200, **kwargs)


def read_trade_files(out):
    """Every trade file as {date: [row dicts]}."""
    result = {}
    for path in sorted((out / TRADE_FEED).glob("date=*/*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            result[path.parent.name.removeprefix("date=")] = list(csv.DictReader(handle))
    return result


def read_counterparty_files(out):
    result = {}
    for path in sorted((out / COUNTERPARTY_FEED).glob("date=*/*.json")):
        lines = path.read_text(encoding="utf-8").splitlines()
        result[path.parent.name.removeprefix("date=")] = [json.loads(line) for line in lines]
    return result


def test_one_trade_file_per_business_day(tmp_path):
    system = make(tmp_path)
    system.advance(5)  # Monday 16 March to Friday 20 March
    export_files(system, tmp_path / "out")
    assert list(read_trade_files(tmp_path / "out")) == [
        "2026-03-16",
        "2026-03-17",
        "2026-03-18",
        "2026-03-19",
        "2026-03-20",
    ]


def test_every_trade_row_is_in_exactly_one_file(tmp_path):
    system = make(tmp_path)
    system.advance(4)
    export_files(system, tmp_path / "out")
    in_files = [
        (row["trade_id"], row["trade_version"])
        for rows in read_trade_files(tmp_path / "out").values()
        for row in rows
    ]
    with sqlite3.connect(system.db_path) as con:
        in_database = [
            (trade_id, str(version))
            for trade_id, version in con.execute("SELECT trade_id, trade_version FROM trades")
        ]
    assert len(in_files) == len(set(in_files))
    assert sorted(in_files) == sorted(in_database)


def test_header_and_values_match_the_database(tmp_path):
    system = make(tmp_path)
    system.advance(1)
    export_files(system, tmp_path / "out")
    path = next((tmp_path / "out" / TRADE_FEED).glob("date=*/*.csv"))
    assert path.read_text(encoding="utf-8").splitlines()[0] == ",".join(TRADE_COLUMNS)
    row = read_trade_files(tmp_path / "out")["2026-03-16"][0]
    with sqlite3.connect(system.db_path) as con:
        source = con.execute(
            "SELECT price, last_modified, counterparty_id FROM trades WHERE trade_id=?"
            " AND trade_version=?",
            (row["trade_id"], row["trade_version"]),
        ).fetchone()
    assert (float(row["price"]), row["last_modified"], row["counterparty_id"]) == source


def test_a_late_row_is_in_the_file_of_the_day_it_arrived(tmp_path):
    system = make(tmp_path, late_rate=0.2)
    system.advance(3)
    export_files(system, tmp_path / "out")
    files = read_trade_files(tmp_path / "out")
    with sqlite3.connect(system.db_path) as con:
        late = con.execute(
            "SELECT trade_id, trade_version, business_date FROM sim_truth WHERE kind='LATE_ROW'"
        ).fetchall()
    assert late, "the test needs at least one late row"
    for trade_id, version, arrival in late:
        found = [
            day
            for day, rows in files.items()
            for row in rows
            if (row["trade_id"], row["trade_version"]) == (trade_id, str(version))
        ]
        assert found == [arrival]
        # Its last_modified is on an earlier day than the file it arrived in.
        row = next(
            r
            for r in files[arrival]
            if (r["trade_id"], r["trade_version"]) == (trade_id, str(version))
        )
        assert row["last_modified"][:10] < arrival


def test_empty_source_values_become_empty_fields(tmp_path):
    system = make(tmp_path, null_rate=0.2)
    system.advance(1)
    export_files(system, tmp_path / "out")
    rows = read_trade_files(tmp_path / "out")["2026-03-16"]
    assert any(row["book_id"] == "" or row["volume"] == "" for row in rows)


def test_counterparty_changes_cover_the_whole_change_log_in_order(tmp_path):
    system = make(tmp_path)
    system.advance(5)
    export_files(system, tmp_path / "out")
    files = read_counterparty_files(tmp_path / "out")
    lsns = [change["lsn"] for rows in files.values() for change in rows]
    with sqlite3.connect(system.db_path) as con:
        rows = con.execute("SELECT lsn FROM cdc_counterparties ORDER BY lsn").fetchall()
    expected = [lsn for (lsn,) in rows]
    assert lsns == expected
    # The initial load of 40 counterparties is in the first file.
    first_day = min(files)
    assert sum(change["operation"] == "I" for change in files[first_day]) >= 40


def test_replaying_the_counterparty_files_rebuilds_the_table(tmp_path):
    system = make(tmp_path)
    system.advance(5)
    export_files(system, tmp_path / "out")
    state = {}
    for day in sorted(read_counterparty_files(tmp_path / "out")):
        for change in read_counterparty_files(tmp_path / "out")[day]:
            if change["operation"] == "D":
                state.pop(change["counterparty_id"], None)
            else:
                state[change["counterparty_id"]] = change["credit_rating"]
    with sqlite3.connect(system.db_path) as con:
        table = dict(con.execute("SELECT counterparty_id, credit_rating FROM counterparties"))
    assert state == table


def test_the_same_seed_gives_identical_files(tmp_path):
    for name in ("one", "two"):
        system = make(tmp_path, name=name)
        system.advance(3)
        export_files(system, tmp_path / f"out_{name}")
    one = sorted((tmp_path / "out_one").rglob("*.*"))
    two = sorted((tmp_path / "out_two").rglob("*.*"))
    assert [p.relative_to(tmp_path / "out_one") for p in one] == [
        p.relative_to(tmp_path / "out_two") for p in two
    ]
    assert [p.read_bytes() for p in one] == [p.read_bytes() for p in two]


def test_running_again_writes_nothing_and_a_new_day_adds_only_its_files(tmp_path):
    system = make(tmp_path)
    system.advance(2)
    out = tmp_path / "out"
    first = export_files(system, out)
    before = {p: p.read_bytes() for p in first}
    assert export_files(system, out) == []

    system.advance(1)
    second = export_files(system, out)
    assert second and not set(second) & set(first)
    assert {p: p.read_bytes() for p in first} == before


def test_force_rewrites_the_same_content(tmp_path):
    system = make(tmp_path)
    system.advance(1)
    out = tmp_path / "out"
    first = export_files(system, out)
    before = {p: p.read_bytes() for p in first}
    again = export_files(system, out, force=True)
    assert sorted(again) == sorted(first)
    assert {p: p.read_bytes() for p in again} == before


def test_no_partial_files_are_left_behind(tmp_path):
    system = make(tmp_path)
    system.advance(2)
    export_files(system, tmp_path / "out")
    assert not list((tmp_path / "out").rglob("_*.part"))


def test_nothing_is_written_before_the_first_day_is_simulated(tmp_path):
    system = make(tmp_path)
    assert export_files(system, tmp_path / "out") == []
