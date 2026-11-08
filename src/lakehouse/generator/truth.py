"""The truth: the right answers that tests compare the pipeline against.

Two things are produced here:

* control totals, one small file per business day, like the end-of-day extract
  a real trading system sends to finance, and
* the truth manifest, a JSON file listing exactly which problems were injected
  and what the correct results are.

The rule used for "correct" (the same steps the Silver layer must follow)
-------------------------------------------------------------------------
1. A row is INVALID if a mandatory field is empty (D04) or the delivery period
   ends before it starts (D05). Invalid rows go to the dead letter queue.
2. Among the valid rows, keep the highest version of each trade.
3. A trade whose latest valid version is CANCELLED is not active.
4. Volumes are converted to the standard unit, counting clock changes (D06, D07).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from lakehouse.generator.defects import NULLABLE_COLUMNS
from lakehouse.generator.trades import (
    BBL_PER_M3,
    LONDON,
    THERM_PER_MWH,
    elapsed_hours,
)

TRADE_TIME_COLUMNS = ["delivery_start", "delivery_end", "last_modified"]
CLOCK_CHANGE_YEARS = (2026, 2027)


# ----------------------------------------------------------------------
# Reading and judging trade rows
# ----------------------------------------------------------------------
def load_trades(con: sqlite3.Connection, table: str = "trades") -> pd.DataFrame:
    """Read a trades table and turn the time columns into real timestamps."""
    frame = pd.read_sql(f"SELECT * FROM {table}", con)
    for column in TRADE_TIME_COLUMNS:
        frame[column] = pd.to_datetime(frame[column])
    return frame


def invalid_mask(frame: pd.DataFrame) -> pd.Series:
    """True for rows the Silver layer must reject (defects D04 and D05)."""
    missing = frame[NULLABLE_COLUMNS].isna().any(axis=1)
    bad_range = frame["delivery_end"] <= frame["delivery_start"]
    return missing | bad_range


def standard_volume(frame: pd.DataFrame, group_of: dict[str, str]) -> pd.Series:
    """Each row's volume in the standard unit, counting clock changes."""
    group = frame["commodity_code"].map(group_of)
    start = frame["delivery_start"].dt.tz_localize(LONDON).dt.tz_convert("UTC")
    end = frame["delivery_end"].dt.tz_localize(LONDON).dt.tz_convert("UTC")
    hours = (end - start).dt.total_seconds() / 3600
    volume = frame["volume"].astype(float)
    result = np.where((group == "POWER") & (frame["unit"] == "MW"), volume * hours, volume)
    result = np.where((group == "GAS") & (frame["unit"] == "MWh"), volume * THERM_PER_MWH, result)
    result = np.where((group == "CRUDE") & (frame["unit"] == "m3"), volume * BBL_PER_M3, result)
    return pd.Series(result, index=frame.index)


def latest_valid(frame: pd.DataFrame) -> pd.DataFrame:
    """The highest valid version of each trade (rules 1 and 2)."""
    valid = frame[~invalid_mask(frame)]
    ordered = valid.sort_values(["trade_id", "trade_version", "last_modified"])
    return ordered.drop_duplicates("trade_id", keep="last")


def active_trades(frame: pd.DataFrame) -> pd.DataFrame:
    """The latest valid version of each trade, without the cancelled ones (rule 3)."""
    latest = latest_valid(frame)
    return latest[latest["status"] != "CANCELLED"]


def book_totals(frame: pd.DataFrame, group_of: dict[str, str], business_date: date) -> pd.DataFrame:
    """The end-of-day control totals: active trades per book, up to now."""
    active = active_trades(frame).copy()
    if active.empty:
        return pd.DataFrame(columns=["business_date", "book_id", "trade_count", "total_volume_std"])
    active["volume_std"] = standard_volume(active, group_of)
    totals = (
        active.groupby("book_id")
        .agg(trade_count=("trade_id", "count"), total_volume_std=("volume_std", "sum"))
        .reset_index()
    )
    totals["total_volume_std"] = totals["total_volume_std"].round(2)
    totals.insert(0, "business_date", business_date.isoformat())
    return totals


def write_control_totals(directory: Path, business_date: date, totals: pd.DataFrame) -> Path:
    """Write the day's control totals as a small CSV file."""
    folder = directory / "control_totals" / f"date={business_date.isoformat()}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "control_totals.csv"
    totals.to_csv(path, index=False)
    return path


# ----------------------------------------------------------------------
# Clock changes (defect D07)
# ----------------------------------------------------------------------
def last_sunday(year: int, month: int) -> date:
    """The UK clocks change on the last Sunday of March and of October."""
    day = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    while day.weekday() != 6:
        day -= timedelta(days=1)
    return day


def settlement_periods(day: date) -> int:
    """Half-hour settlement periods in a UK day: normally 48, 46 or 50 on clock changes."""
    start = datetime(day.year, day.month, day.day)
    hours = elapsed_hours(start, start + timedelta(days=1))
    return round(hours * 2)


def clock_changes() -> dict[str, int]:
    """The clock change days, with how many settlement periods each has."""
    result = {}
    for year in CLOCK_CHANGE_YEARS:
        for month in (3, 10):
            day = last_sunday(year, month)
            result[day.isoformat()] = settlement_periods(day)
    return result


# ----------------------------------------------------------------------
# The truth manifest
# ----------------------------------------------------------------------
def _summary(frame: pd.DataFrame, group_of: dict[str, str]) -> dict:
    """The expected results for a set of trade rows."""
    invalid = invalid_mask(frame)
    latest = latest_valid(frame)
    active = active_trades(frame).copy()
    active["volume_std"] = standard_volume(active, group_of) if len(active) else []
    by_commodity = active.groupby("commodity_code")["volume_std"].sum().round(2)
    return {
        "rows": len(frame),
        "rejected_rows": int(invalid.sum()),
        "valid_rows": int((~invalid).sum()),
        "trades_with_a_valid_row": len(latest),
        "cancelled_trades": int((latest["status"] == "CANCELLED").sum()),
        "active_trades": len(active),
        "standard_volume_by_commodity": {code: float(v) for code, v in by_commodity.items()},
    }


def _keys(rows: list[tuple]) -> list[dict]:
    return [{"trade_id": r[0], "trade_version": r[1], "detail": r[2]} for r in rows]


def build_truth(db_path: str | Path) -> dict:
    """Work out the truth manifest from the source database."""
    with sqlite3.connect(db_path) as con:
        config = json.loads(
            con.execute("SELECT value FROM sim_state WHERE key='config'").fetchone()[0]
        )
        state = json.loads(
            con.execute("SELECT value FROM sim_state WHERE key='state'").fetchone()[0]
        )
        trades = load_trades(con)
        deleted = load_trades(con, "sim_deleted_trades").drop(columns=["deleted_on"])
        commodities = pd.read_sql(
            "SELECT commodity_code, commodity_group, native_units FROM commodities", con
        )
        truth = pd.read_sql("SELECT * FROM sim_truth ORDER BY rowid", con)

    group_of = dict(zip(commodities["commodity_code"], commodities["commodity_group"], strict=True))
    stats = state["stats"]

    def of_kind(kind: str) -> list[tuple]:
        part = truth[truth["kind"] == kind]
        return list(zip(part["trade_id"], part["trade_version"], part["detail"], strict=True))

    def events(kind: str) -> list[dict]:
        part = truth[truth["kind"] == kind]
        return [
            {"business_date": d, "id": i}
            for d, i in zip(part["business_date"], part["detail"], strict=True)
        ]

    valid = trades[~invalid_mask(trades)]
    non_standard = (
        valid.assign(group=valid["commodity_code"].map(group_of))
        .groupby(["group", "unit"])
        .size()
        .reset_index(name="rows")
    )
    standard = {"POWER": "MWh", "GAS": "therm", "CRUDE": "bbl", "EMISSIONS": "tCO2e"}
    non_standard = non_standard[
        non_standard.apply(lambda r: standard[r["group"]] != r["unit"], axis=1)
    ]

    mw = valid[(valid["commodity_code"].map(group_of) == "POWER") & (valid["unit"] == "MW")]
    naive_hours = (mw["delivery_end"] - mw["delivery_start"]).dt.total_seconds() / 3600
    start_utc = mw["delivery_start"].dt.tz_localize(LONDON).dt.tz_convert("UTC")
    end_utc = mw["delivery_end"].dt.tz_localize(LONDON).dt.tz_convert("UTC")
    true_hours = (end_utc - start_utc).dt.total_seconds() / 3600
    spanning = int((naive_hours != true_hours).sum())

    pipeline_view = pd.concat([trades, deleted], ignore_index=True)

    return {
        "meta": {
            "seed": config["seed"],
            "trades_per_day": config["trades_per_day"],
            "days_simulated": stats["days"],
            "next_business_date": config["next_day"],
            "note": "Written by the simulator. Pipeline code must never read this file.",
        },
        "defects": {
            "D01_amendments": {
                "trades_amended": stats["amended_trades"],
                "amendment_rows": stats["amendments"],
            },
            "D02_cancellations": {"cancellation_rows": stats["cancellations"]},
            "D03_late_rows": {
                "count": len(of_kind("LATE_ROW")),
                "rows": _keys(of_kind("LATE_ROW")),
            },
            "D04_empty_mandatory_field": {
                "count": len(of_kind("NULL_FIELD")),
                "rows": _keys(of_kind("NULL_FIELD")),
            },
            "D05_delivery_end_before_start": {
                "count": len(of_kind("BAD_DELIVERY_RANGE")),
                "rows": _keys(of_kind("BAD_DELIVERY_RANGE")),
            },
            "D06_mixed_units": {
                "rows_in_a_non_standard_unit": [
                    {"commodity_group": r["group"], "unit": r["unit"], "rows": int(r["rows"])}
                    for _, r in non_standard.iterrows()
                ]
            },
            "D07_clock_changes": {
                "settlement_periods_on_clock_change_days": clock_changes(),
                "mw_rows_whose_period_contains_a_clock_change": spanning,
            },
            "D08_counterparty_downgrade": events("DOWNGRADE"),
            "D14_orphan_counterparty": {
                "count": len(of_kind("ORPHAN_COUNTERPARTY")),
                "rows": _keys(of_kind("ORPHAN_COUNTERPARTY")),
            },
            "D16_counterparty_deleted": events("DELETE"),
            "D17_trades_hard_deleted": {
                "count": len(deleted),
                "trade_ids": sorted(deleted["trade_id"].unique().tolist()),
            },
            "other_reference_data_changes": {
                "book_moved_desk": events("BOOK_REMAP"),
                "counterparty_onboarded": events("ONBOARD"),
                "limit_changes": len(events("LIMIT_CHANGE")),
                "rating_changes": len(events("RATING_CHANGE")),
            },
        },
        "expected": {
            "source_now": _summary(trades, group_of),
            "pipeline_view": _summary(pipeline_view, group_of),
            "explanation": (
                "source_now is what the source holds today and what the control totals match. "
                "pipeline_view also includes trades that were hard deleted (D17) after a daily "
                "load had already copied them, which is what a watermark pipeline will hold."
            ),
        },
    }


def write_truth(directory: str | Path, db_path: str | Path) -> Path:
    """Write the truth manifest to <directory>/_truth/defects.json."""
    folder = Path(directory) / "_truth"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "defects.json"
    path.write_text(json.dumps(build_truth(db_path), indent=2, sort_keys=False) + "\n")
    return path
