"""Tests for the injected defects, the control totals and the truth manifest."""

import json
import sqlite3
from datetime import date, datetime

import pandas as pd
import pytest

from lakehouse.generator.cli import main
from lakehouse.generator.defects import NULLABLE_COLUMNS, DefectInjector
from lakehouse.generator.source_db import SourceSystem
from lakehouse.generator.trades import (
    TRADE_COLUMNS,
    business_days,
    elapsed_hours,
    to_standard_volume,
)
from lakehouse.generator.truth import (
    active_trades,
    book_totals,
    build_truth,
    clock_changes,
    invalid_mask,
    last_sunday,
    load_trades,
    settlement_periods,
    standard_volume,
)

# High rates, so that a small simulation contains plenty of every defect.
SETTINGS = {
    "trades_per_day": 500,
    "null_rate": 0.01,
    "bad_range_rate": 0.01,
    "orphan_rate": 0.01,
    "hard_delete_day": date(2026, 3, 23),
    "hard_delete_count": 3,
}
LAST_DAY = date(2026, 3, 27)


def advance_until(system, last_day):
    return system.advance(len(business_days(system.next_business_date, last_day)))


def query(system, sql, params=()):
    with sqlite3.connect(system.db_path) as con:
        return con.execute(sql, params).fetchall()


@pytest.fixture(scope="module")
def system(tmp_path_factory):
    source = SourceSystem.create(tmp_path_factory.mktemp("truth") / "src", **SETTINGS)
    advance_until(source, LAST_DAY)
    return source


@pytest.fixture(scope="module")
def manifest(system):
    return build_truth(system.db_path)


def keys(entries):
    return {(e["trade_id"], e["trade_version"]) for e in entries}


# --- D04, D05, D14: spoiled rows ---


def test_every_empty_mandatory_field_was_injected_and_nothing_else(system, manifest):
    in_database = set(
        query(
            system,
            "SELECT trade_id, trade_version FROM trades WHERE book_id IS NULL "
            "OR commodity_code IS NULL OR volume IS NULL OR unit IS NULL "
            "OR delivery_start IS NULL",
        )
    )
    injected = manifest["defects"]["D04_empty_mandatory_field"]
    assert injected["count"] > 0
    assert keys(injected["rows"]) == in_database


def test_the_named_column_really_is_empty(system, manifest):
    for entry in manifest["defects"]["D04_empty_mandatory_field"]["rows"]:
        assert entry["detail"] in NULLABLE_COLUMNS
        (value,) = query(
            system,
            f"SELECT {entry['detail']} FROM trades WHERE trade_id = ? AND trade_version = ?",
            (entry["trade_id"], entry["trade_version"]),
        )[0]
        assert value is None


def test_every_bad_delivery_range_was_injected_and_nothing_else(system, manifest):
    in_database = set(
        query(
            system,
            "SELECT trade_id, trade_version FROM trades WHERE delivery_end <= delivery_start",
        )
    )
    injected = manifest["defects"]["D05_delivery_end_before_start"]
    assert injected["count"] > 0
    assert keys(injected["rows"]) == in_database


def test_every_orphan_counterparty_was_injected_and_nothing_else(system, manifest):
    in_database = set(
        query(
            system,
            "SELECT trade_id, trade_version FROM trades WHERE counterparty_id LIKE 'CP-9%'",
        )
    )
    injected = manifest["defects"]["D14_orphan_counterparty"]
    assert injected["count"] > 0
    assert keys(injected["rows"]) == in_database
    assert all(e["detail"].startswith("CP-9") for e in injected["rows"])


def test_an_orphan_counterparty_really_does_not_exist(system, manifest):
    known = {row[0] for row in query(system, "SELECT counterparty_id FROM cdc_counterparties")}
    for entry in manifest["defects"]["D14_orphan_counterparty"]["rows"]:
        assert entry["detail"] not in known


def test_rejected_rows_in_the_manifest_match_the_injected_defects(system, manifest):
    defects = manifest["defects"]
    expected = (
        defects["D04_empty_mandatory_field"]["count"]
        + defects["D05_delivery_end_before_start"]["count"]
    )
    # rejected_rows is worked out from the data. It is not just a copy of the counts.
    assert manifest["expected"]["source_now"]["rejected_rows"] == expected


def test_a_spoiled_row_does_not_pass_its_problem_on_to_later_versions(system, manifest):
    injected = keys(manifest["defects"]["D04_empty_mandatory_field"]["rows"])
    checked = 0
    for trade_id, version in injected:
        later = query(
            system,
            "SELECT trade_version, book_id, commodity_code, volume, unit, delivery_start "
            "FROM trades WHERE trade_id = ? AND trade_version > ?",
            (trade_id, version),
        )
        for later_version, *values in later:
            if (trade_id, later_version) in injected:
                continue  # that row was spoiled by its own, separate injection
            checked += 1
            assert None not in values
    assert checked > 0


def test_no_defects_are_injected_when_the_rates_are_zero(tmp_path):
    source = SourceSystem.create(
        tmp_path / "clean",
        trades_per_day=300,
        null_rate=0,
        bad_range_rate=0,
        orphan_rate=0,
        hard_delete_count=0,
    )
    results = advance_until(source, LAST_DAY)
    assert sum(r.defects_injected for r in results) == 0
    assert sum(r.trades_deleted for r in results) == 0


# --- D17: hard deleted trades ---


def test_hard_deleted_trades_are_gone_from_the_source_but_kept_as_proof(system, manifest):
    deleted = manifest["defects"]["D17_trades_hard_deleted"]
    assert deleted["count"] == 3
    for trade_id in deleted["trade_ids"]:
        assert query(system, "SELECT 1 FROM trades WHERE trade_id = ?", (trade_id,)) == []
        assert query(system, "SELECT 1 FROM sim_deleted_trades WHERE trade_id = ?", (trade_id,))


def test_the_deletion_happens_once_on_the_chosen_day(system):
    days = query(system, "SELECT DISTINCT deleted_on FROM sim_deleted_trades")
    assert days == [("2026-03-23",)]


def test_a_deleted_trade_is_never_recreated_or_amended_later(system, manifest):
    for trade_id in manifest["defects"]["D17_trades_hard_deleted"]["trade_ids"]:
        assert (
            query(system, "SELECT COUNT(*) FROM trades WHERE trade_id = ?", (trade_id,))[0][0] == 0
        )


def test_the_pipeline_view_still_holds_the_deleted_trades(manifest):
    source = manifest["expected"]["source_now"]
    pipeline = manifest["expected"]["pipeline_view"]
    assert pipeline["active_trades"] - source["active_trades"] == 3


# --- control totals ---


def test_a_control_totals_file_is_written_for_every_day(system):
    folders = sorted((system.directory / "control_totals").iterdir())
    expected_days = [d.isoformat() for d in business_days(date(2026, 3, 16), LAST_DAY)]
    assert [f.name.removeprefix("date=") for f in folders] == expected_days


def test_the_last_control_totals_match_the_manifest(system, manifest):
    totals = pd.read_csv(
        system.directory / "control_totals" / f"date={LAST_DAY.isoformat()}" / "control_totals.csv"
    )
    assert totals["trade_count"].sum() == manifest["expected"]["source_now"]["active_trades"]
    total_volume = sum(manifest["expected"]["source_now"]["standard_volume_by_commodity"].values())
    assert totals["total_volume_std"].sum() == pytest.approx(total_volume, rel=1e-9)


def test_the_control_totals_see_the_hard_delete_that_a_watermark_cannot(system, manifest):
    """The reason the control totals exist (defect D17)."""
    totals = pd.read_csv(
        system.directory / "control_totals" / f"date={LAST_DAY.isoformat()}" / "control_totals.csv"
    )
    pipeline_count = manifest["expected"]["pipeline_view"]["active_trades"]
    assert pipeline_count - totals["trade_count"].sum() == 3


def test_control_totals_grow_as_trades_accumulate(system):
    def total(day):
        path = system.directory / "control_totals" / f"date={day}" / "control_totals.csv"
        return pd.read_csv(path)["trade_count"].sum()

    assert total("2026-03-17") > total("2026-03-16")


# --- D06 and D07: units and clock changes ---


def test_the_vectorised_volume_agrees_with_the_one_row_function(system):
    with sqlite3.connect(system.db_path) as con:
        trades = load_trades(con)
        groups = dict(con.execute("SELECT commodity_code, commodity_group FROM commodities"))
    valid = trades[~invalid_mask(trades)].head(3000)
    fast = standard_volume(valid, groups)
    for position, row in enumerate(valid.itertuples()):
        slow = to_standard_volume(
            row.volume,
            row.unit,
            groups[row.commodity_code],
            row.delivery_start.to_pydatetime(),
            row.delivery_end.to_pydatetime(),
        )
        assert fast.iloc[position] == pytest.approx(slow)


def test_a_month_containing_the_clock_change_is_one_hour_shorter():
    assert elapsed_hours(datetime(2026, 3, 1), datetime(2026, 4, 1)) == 743  # not 744
    assert elapsed_hours(datetime(2026, 10, 1), datetime(2026, 11, 1)) == 745  # not 744


def test_a_power_trade_in_mw_uses_the_real_hours():
    start, end = datetime(2026, 3, 1), datetime(2026, 4, 1)
    assert to_standard_volume(10, "MW", "POWER", start, end) == 7430


def test_clock_change_days_have_46_and_50_settlement_periods():
    assert last_sunday(2026, 3) == date(2026, 3, 29)
    assert last_sunday(2026, 10) == date(2026, 10, 25)
    assert settlement_periods(date(2026, 3, 29)) == 46
    assert settlement_periods(date(2026, 10, 25)) == 50
    assert settlement_periods(date(2026, 6, 10)) == 48
    assert clock_changes()["2026-03-29"] == 46


def test_the_manifest_counts_mw_rows_that_a_simple_subtraction_gets_wrong(system, manifest):
    with sqlite3.connect(system.db_path) as con:
        trades = load_trades(con)
        groups = dict(con.execute("SELECT commodity_code, commodity_group FROM commodities"))
    valid = trades[~invalid_mask(trades)]
    mw = valid[(valid["commodity_code"].map(groups) == "POWER") & (valid["unit"] == "MW")]
    wrong = 0
    for row in mw.itertuples():
        start, end = row.delivery_start.to_pydatetime(), row.delivery_end.to_pydatetime()
        naive = (end - start).total_seconds() / 3600
        if naive != elapsed_hours(start, end):
            wrong += 1
    reported = manifest["defects"]["D07_clock_changes"][
        "mw_rows_whose_period_contains_a_clock_change"
    ]
    assert wrong > 0
    assert reported == wrong


# --- the rules of the truth ---


def test_active_trades_never_include_a_cancelled_latest_version(system):
    with sqlite3.connect(system.db_path) as con:
        trades = load_trades(con)
    active = active_trades(trades)
    assert (active["status"] != "CANCELLED").all()
    assert active["trade_id"].is_unique


def test_book_totals_of_nothing_is_an_empty_table():
    empty = pd.DataFrame(columns=TRADE_COLUMNS)
    for column in ("delivery_start", "delivery_end", "last_modified"):
        empty[column] = pd.to_datetime(empty[column])
    result = book_totals(empty, {}, date(2026, 3, 16))
    assert result.empty


# --- the manifest itself ---


def test_the_manifest_is_valid_json_with_the_expected_sections(system):
    path = system.write_truth_manifest()
    assert path == system.directory / "_truth" / "defects.json"
    content = json.loads(path.read_text())
    assert set(content) == {"meta", "defects", "expected"}
    assert {"D01_amendments", "D04_empty_mandatory_field", "D17_trades_hard_deleted"} <= set(
        content["defects"]
    )
    assert set(content["expected"]) == {"source_now", "pipeline_view", "explanation"}


def test_the_manifest_matches_the_simulator_counts(system, manifest):
    (new_trades,) = query(system, "SELECT COUNT(*) FROM trades WHERE trade_version = 1")[0]
    stats = manifest["defects"]
    assert stats["D03_late_rows"]["count"] == len(stats["D03_late_rows"]["rows"])
    amendment_rows = query(system, "SELECT COUNT(*) FROM trades WHERE status = 'AMENDED'")[0][0]
    assert stats["D01_amendments"]["amendment_rows"] >= amendment_rows  # spoiled rows still count
    assert new_trades > 0


def test_the_same_settings_give_the_same_manifest(tmp_path):
    a = SourceSystem.create(tmp_path / "a", **SETTINGS)
    b = SourceSystem.create(tmp_path / "b", **SETTINGS)
    advance_until(a, LAST_DAY)
    advance_until(b, LAST_DAY)
    assert build_truth(a.db_path) == build_truth(b.db_path)


def test_stopping_and_restarting_gives_the_same_manifest(tmp_path):
    straight = SourceSystem.create(tmp_path / "a", **SETTINGS)
    advance_until(straight, LAST_DAY)

    stopped = SourceSystem.create(tmp_path / "b", **SETTINGS)
    advance_until(stopped, date(2026, 3, 20))
    reopened = SourceSystem(tmp_path / "b")
    advance_until(reopened, LAST_DAY)

    assert build_truth(straight.db_path) == build_truth(reopened.db_path)


# --- the injector on its own ---


def make_frame(count=2000):
    rows = []
    for number in range(count):
        rows.append(
            {
                "trade_id": f"TRD-PWR-{number:06d}",
                "trade_version": 1 if number % 2 == 0 else 2,
                "book_id": "BK-UKPWR-01",
                "commodity_code": "GB_PWR_BL",
                "buy_sell": "BUY",
                "volume": 50.0,
                "unit": "MW",
                "price": 70.0,
                "currency": "GBP",
                "delivery_start": datetime(2026, 5, 1),
                "delivery_end": datetime(2026, 6, 1),
                "counterparty_id": "CP-00001",
                "trader_id": "TR-5001",
                "status": "CONFIRMED",
                "trade_date": date(2026, 3, 16),
                "last_modified": datetime(2026, 3, 16, 10),
            }
        )
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def test_spoil_leaves_the_original_table_unchanged():
    frame = make_frame()
    before = frame.copy()
    DefectInjector(1, null_rate=0.1, bad_range_rate=0.1, orphan_rate=0.1).spoil(frame)
    pd.testing.assert_frame_equal(frame, before)


def test_a_row_gets_at_most_one_defect():
    _, injections = DefectInjector(1, null_rate=0.2, bad_range_rate=0.2, orphan_rate=0.2).spoil(
        make_frame()
    )
    seen = [(i.trade_id, i.trade_version) for i in injections]
    assert len(seen) == len(set(seen))
    assert len(seen) > 0


def test_orphans_only_appear_on_brand_new_trades():
    _, injections = DefectInjector(1, null_rate=0, bad_range_rate=0, orphan_rate=0.5).spoil(
        make_frame()
    )
    assert injections
    assert all(i.kind == "ORPHAN_COUNTERPARTY" and i.trade_version == 1 for i in injections)


def test_the_injector_rates_are_roughly_right():
    frame = make_frame(20000)
    _, injections = DefectInjector(7, null_rate=0.01, bad_range_rate=0, orphan_rate=0).spoil(frame)
    assert 120 < len(injections) < 280  # about 200


# --- the command line ---


def test_command_line_writes_the_manifest(tmp_path, capsys):
    folder = str(tmp_path / "cli")
    assert main(["init", "--dir", folder, "--trades-per-day", "50"]) == 0
    assert main(["advance", "--dir", folder, "--days", "2"]) == 0
    assert (tmp_path / "cli" / "_truth" / "defects.json").exists()
    assert main(["manifest", "--dir", folder]) == 0
    assert "Truth manifest written" in capsys.readouterr().out
