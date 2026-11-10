"""Daily files for the landing zone (CSV and JSON).

Some systems send data as files instead of letting a pipeline read their database. This module
writes two such feeds from the source system, one folder per business day:

    trade_feed/date=2026-03-16/trades_20260316.csv
    counterparty_changes/date=2026-03-16/counterparties_20260316.json

The trade feed holds the trade rows that reached the system that day. A late row (defect D03)
is in the file of the day it arrived, not the day of its `last_modified`, exactly as in the
database. The counterparty feed holds that day's changes from the change log, one JSON object
per line (JSON Lines), in `lsn` order. The first file also holds the initial load.

A file is written once. Running the export again skips files that exist, so a pipeline that
reads each file once never sees a file change. The content is the same on every run.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

from lakehouse.generator.source_db import SourceSystem
from lakehouse.generator.trades import TRADE_COLUMNS, is_business_day

TRADE_FEED = "trade_feed"
COUNTERPARTY_FEED = "counterparty_changes"

COUNTERPARTY_CHANGE_COLUMNS = [
    "lsn",
    "commit_time",
    "operation",
    "counterparty_id",
    "counterparty_name",
    "country_of_risk",
    "credit_rating",
    "credit_limit_gbp",
    "is_active",
    "effective_from",
]

# Trades with their arrival day: late rows arrive on a later day than their last_modified.
TRADES_WITH_ARRIVAL = f"""
SELECT {", ".join("t." + c for c in TRADE_COLUMNS)},
       COALESCE(l.arrival_date, substr(t.last_modified, 1, 10)) AS arrival_date
FROM trades t
LEFT JOIN (
    SELECT trade_id, trade_version, MIN(business_date) AS arrival_date
    FROM sim_truth WHERE kind = 'LATE_ROW' GROUP BY trade_id, trade_version
) l ON l.trade_id = t.trade_id AND l.trade_version = t.trade_version
ORDER BY t.trade_id, t.trade_version
"""


def export_files(system: SourceSystem, out_dir: str | Path, force: bool = False) -> list[Path]:
    """Write the daily files that do not exist yet. Returns the files written, oldest first."""
    out = Path(out_dir)
    written: list[Path] = []
    with sqlite3.connect(system.db_path) as con:
        days = _simulated_days(con, system.next_business_date)
        trades = _group(con.execute(TRADES_WITH_ARRIVAL).fetchall(), len(TRADE_COLUMNS))
        changes = _counterparty_changes_by_day(con, days[0] if days else None)

    for day in days:
        key = day.isoformat()
        compact = day.strftime("%Y%m%d")
        if key in trades:
            path = out / TRADE_FEED / f"date={key}" / f"trades_{compact}.csv"
            if _write(path, _csv_text(trades[key]), force):
                written.append(path)
        if key in changes:
            path = out / COUNTERPARTY_FEED / f"date={key}" / f"counterparties_{compact}.json"
            if _write(path, _json_lines_text(changes[key]), force):
                written.append(path)
    return written


def _simulated_days(con: sqlite3.Connection, next_day: date) -> list[date]:
    """Every business day from the first trade up to the day before the next one to simulate."""
    first = con.execute("SELECT MIN(substr(last_modified, 1, 10)) FROM trades").fetchone()[0]
    if first is None:
        return []
    days = []
    current = date.fromisoformat(first)
    while current < next_day:
        if is_business_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def _group(rows: list[tuple], width: int) -> dict[str, list[tuple]]:
    """Group rows by their last column (the arrival day), without that column."""
    grouped: dict[str, list[tuple]] = {}
    for row in rows:
        grouped.setdefault(row[width], []).append(row[:width])
    return grouped


def _counterparty_changes_by_day(
    con: sqlite3.Connection, first_day: date | None
) -> dict[str, list[tuple]]:
    """Change log rows by the day they reach the file. The initial load goes in the first file."""
    if first_day is None:
        return {}
    first = first_day.isoformat()
    rows = con.execute(
        f"SELECT {', '.join(COUNTERPARTY_CHANGE_COLUMNS)} FROM cdc_counterparties ORDER BY lsn"
    ).fetchall()
    grouped: dict[str, list[tuple]] = {}
    for row in rows:
        day = max(row[1][:10], first)
        grouped.setdefault(day, []).append(row)
    return grouped


def _csv_text(rows: Iterable[tuple]) -> str:
    """CSV with a header row. An empty source value becomes an empty field."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TRADE_COLUMNS)
    for row in rows:
        writer.writerow("" if value is None else value for value in row)
    return buffer.getvalue()


def _json_lines_text(rows: Iterable[tuple]) -> str:
    """One JSON object per line."""
    lines = (
        json.dumps(dict(zip(COUNTERPARTY_CHANGE_COLUMNS, row, strict=True)), ensure_ascii=False)
        for row in rows
    )
    return "\n".join(lines) + "\n"


def _write(path: Path, text: str, force: bool) -> bool:
    """Write a file so it never appears half written. Returns False if it already existed."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    # A name that starts with an underscore is ignored by Auto Loader, so a reader never sees
    # the file until the rename makes it complete.
    partial = path.with_name("_" + path.name + ".part")
    partial.write_text(text, encoding="utf-8", newline="\n")
    os.replace(partial, path)
    return True
