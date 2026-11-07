"""Tests for the trade simulator."""

from datetime import date, datetime

import pandas as pd
import pytest

from lakehouse.generator.reference import generate_reference
from lakehouse.generator.trades import (
    BBL_PER_M3,
    THERM_PER_MWH,
    TRADE_COLUMNS,
    TradeSimulator,
    add_business_days,
    business_days,
    is_business_day,
    to_standard_volume,
)

START = date(2026, 3, 16)  # a Monday
END = date(2026, 4, 10)


@pytest.fixture(scope="module")
def reference():
    return generate_reference()


def run(reference, trades_per_day=300, seed=42, start=START, end=END):
    """Simulate a period and return (all rows together, the simulator)."""
    sim = TradeSimulator(reference, seed=seed, trades_per_day=trades_per_day)
    frames = [sim.simulate_day(day) for day in business_days(start, end)]
    return pd.concat(frames, ignore_index=True), sim


# --- business days -------------------------------------------------------


def test_business_days_skip_weekends():
    days = business_days(date(2026, 3, 16), date(2026, 3, 22))
    assert len(days) == 5
    assert all(is_business_day(d) for d in days)


def test_add_business_days_skips_the_weekend():
    friday = date(2026, 3, 20)
    assert add_business_days(friday, 1) == date(2026, 3, 23)  # the Monday


# --- the shape of the data ----------------------------------------------


def test_columns_are_as_documented(reference):
    rows, _ = run(reference, trades_per_day=50, end=date(2026, 3, 17))
    assert list(rows.columns) == TRADE_COLUMNS


def test_same_seed_gives_identical_data(reference):
    a, _ = run(reference, trades_per_day=100, seed=5, end=date(2026, 3, 24))
    b, _ = run(reference, trades_per_day=100, seed=5, end=date(2026, 3, 24))
    pd.testing.assert_frame_equal(a, b)


def test_different_seed_gives_different_data(reference):
    a, _ = run(reference, trades_per_day=100, seed=5, end=date(2026, 3, 18))
    b, _ = run(reference, trades_per_day=100, seed=6, end=date(2026, 3, 18))
    assert not a.equals(b)


def test_trade_ids_follow_the_pattern(reference):
    rows, _ = run(reference, trades_per_day=200, end=date(2026, 3, 18))
    assert rows["trade_id"].str.fullmatch(r"TRD-[A-Z]{3}-\d{6}").all()


def test_no_missing_values(reference):
    rows, _ = run(reference, trades_per_day=200, end=date(2026, 3, 18))
    assert rows.notna().all().all()


def test_references_point_to_real_books_and_counterparties(reference):
    rows, _ = run(reference, trades_per_day=200, end=date(2026, 3, 18))
    assert rows["book_id"].isin(reference.books["book_id"]).all()
    assert rows["counterparty_id"].isin(reference.counterparties["counterparty_id"]).all()
    assert rows["commodity_code"].isin(reference.commodities["commodity_code"]).all()


def test_units_are_allowed_for_the_commodity(reference):
    rows, _ = run(reference, trades_per_day=300, end=date(2026, 3, 18))
    allowed = {
        r.commodity_code: set(r.native_units.split("|")) for r in reference.commodities.itertuples()
    }
    assert all(row.unit in allowed[row.commodity_code] for row in rows.itertuples())


def test_each_desk_trades_only_its_own_commodities(reference):
    rows, _ = run(reference, trades_per_day=300, end=date(2026, 3, 18))
    desk = rows.merge(reference.books[["book_id", "desk_code"]], on="book_id")
    power = desk[desk["desk_code"] == "UKPWR"]["commodity_code"]
    assert set(power) <= {"GB_PWR_BL", "GB_PWR_PK"}


def test_delivery_end_is_after_delivery_start(reference):
    rows, _ = run(reference, trades_per_day=300, end=date(2026, 3, 18))
    assert (rows["delivery_end"] > rows["delivery_start"]).all()


def test_gas_delivery_starts_at_five_in_the_morning(reference):
    rows, _ = run(reference, trades_per_day=300, end=date(2026, 3, 18))
    gas = rows[rows["commodity_code"].isin(["NBP_GAS", "TTF_GAS"])]
    assert (gas["delivery_start"].dt.hour == 5).all()


def test_volumes_and_prices_are_positive(reference):
    rows, _ = run(reference, trades_per_day=300, end=date(2026, 3, 18))
    assert (rows["volume"] > 0).all()
    assert (rows["price"] > 0).all()


# --- amendments and cancellations (defects D01 and D02) ------------------


def test_every_trade_starts_at_version_one(reference):
    rows, _ = run(reference)
    first = rows.sort_values("trade_version").groupby("trade_id").first()
    assert (first["trade_version"] == 1).all()


def test_versions_have_no_gaps(reference):
    rows, _ = run(reference)
    for _, group in rows.groupby("trade_id"):
        assert sorted(group["trade_version"]) == list(range(1, len(group) + 1))


def test_some_trades_are_amended_and_some_cancelled(reference):
    rows, sim = run(reference, trades_per_day=500)
    assert sim.stats.amendments > 0
    assert sim.stats.cancellations > 0
    assert (rows["status"] == "AMENDED").sum() == sim.stats.amendments
    assert (rows["status"] == "CANCELLED").sum() == sim.stats.cancellations


def test_amendment_share_is_close_to_the_target(reference):
    _, sim = run(reference, trades_per_day=500)
    # Some amendments fall after the end of the simulation, so allow a margin.
    share = sim.stats.amended_trades / sim.stats.new_trades
    assert 0.04 < share < 0.10


def test_stats_match_the_rows(reference):
    rows, sim = run(reference, trades_per_day=200)
    assert sim.stats.rows == len(rows)
    assert sim.stats.new_trades == (rows["trade_version"] == 1).sum()
    assert sim.stats.rows == (sim.stats.new_trades + sim.stats.amendments + sim.stats.cancellations)


def test_nothing_happens_after_a_cancellation(reference):
    rows, _ = run(reference, trades_per_day=500)
    cancelled = rows[rows["status"] == "CANCELLED"]
    for row in cancelled.itertuples():
        later = rows[
            (rows["trade_id"] == row.trade_id) & (rows["trade_version"] > row.trade_version)
        ]
        assert later.empty


def test_a_new_version_is_written_after_the_old_one(reference):
    rows, _ = run(reference, trades_per_day=300)
    ordered = rows.sort_values(["trade_id", "trade_version"])
    gaps = ordered.groupby("trade_id")["last_modified"].diff().dropna()
    assert (gaps >= pd.Timedelta(0)).all()


def test_amended_rows_keep_the_same_trade_details(reference):
    rows, _ = run(reference, trades_per_day=300)
    keys = ["book_id", "commodity_code", "buy_sell", "counterparty_id", "trader_id", "trade_date"]
    assert (rows.groupby("trade_id")[keys].nunique() == 1).all().all()


# --- simulator rules -----------------------------------------------------


def test_days_must_be_simulated_in_order(reference):
    sim = TradeSimulator(reference, trades_per_day=10)
    sim.simulate_day(date(2026, 3, 17))
    with pytest.raises(ValueError):
        sim.simulate_day(date(2026, 3, 16))


def test_weekends_are_rejected(reference):
    sim = TradeSimulator(reference, trades_per_day=10)
    with pytest.raises(ValueError):
        sim.simulate_day(date(2026, 3, 21))  # a Saturday


# --- the truth about volumes ---------------------------------------------


def test_power_in_mw_becomes_mwh_over_the_delivery_period():
    start, end = datetime(2026, 5, 1), datetime(2026, 5, 2)  # 24 hours
    assert to_standard_volume(50, "MW", "POWER", start, end) == 1200
    assert to_standard_volume(1200, "MWh", "POWER", start, end) == 1200


def test_gas_mwh_becomes_therms():
    start, end = datetime(2026, 5, 1, 5), datetime(2026, 6, 1, 5)
    assert to_standard_volume(10, "MWh", "GAS", start, end) == pytest.approx(10 * THERM_PER_MWH)
    assert to_standard_volume(10, "therm", "GAS", start, end) == 10


def test_crude_cubic_metres_become_barrels():
    start, end = datetime(2026, 5, 1), datetime(2026, 6, 1)
    assert to_standard_volume(10, "m3", "CRUDE", start, end) == pytest.approx(10 * BBL_PER_M3)
    assert to_standard_volume(10, "bbl", "CRUDE", start, end) == 10
