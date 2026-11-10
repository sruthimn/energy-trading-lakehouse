"""Changes to reference data over time (onboarding, downgrades, deletions, desk moves).

This module decides what changes each day. source_db.py applies the changes and writes them to
the change log (CDC).

Scripted events: 19 Mar a book moves desk, 24 Mar a counterparty is downgraded (D08), 26 Mar a
counterparty is onboarded, 6 Apr a counterparty is deleted (D16). Small random limit and rating
changes happen on other days.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from lakehouse.generator.reference import (
    COUNTRIES,
    EXTRA_NAME_STARTS,
    NAME_SECTORS,
    RATINGS,
)
from lakehouse.generator.rng_state import decode_rng, encode_rng

RATING_ORDER = [rating for rating, _ in RATINGS]  # safest first
BASE_LIMIT = dict(RATINGS)

COUNTERPARTY_COLUMNS = [
    "counterparty_id",
    "counterparty_name",
    "country_of_risk",
    "credit_rating",
    "credit_limit_gbp",
    "is_active",
    "effective_from",
]
BOOK_COLUMNS = [
    "book_id",
    "book_name",
    "desk_code",
    "trader_group",
    "is_active",
    "effective_from",
]
TABLE_COLUMNS = {"counterparties": COUNTERPARTY_COLUMNS, "books": BOOK_COLUMNS}
TABLE_KEY = {"counterparties": "counterparty_id", "books": "book_id"}

DEFAULT_BOOK_REMAP_DAY = date(2026, 3, 19)
DEFAULT_DOWNGRADE_DAY = date(2026, 3, 24)
DEFAULT_ONBOARD_DAY = date(2026, 3, 26)
DEFAULT_DELETE_DAY = date(2026, 4, 6)

LIMIT_CHANGE_RATE = 0.005  # chance per counterparty per day
RATING_CHANGE_RATE = 0.003

# Fixed times for scripted events. The deletion is after trading hours, so no
# trade is ever booked with a counterparty that has already been deleted.
ONBOARD_TIME = (8, 30)
BOOK_REMAP_TIME = (9, 0)
DOWNGRADE_TIME = (10, 15)
DELETE_TIME = (18, 30)


@dataclass(frozen=True)
class Change:
    """One change to one row of a reference table."""

    table: str  # "counterparties" or "books"
    operation: str  # "I" insert, "U" update, "D" delete
    row: dict  # the row after the change (for a delete: the row as it was)
    commit_time: datetime
    kind: str  # what kind of event this was, for the truth record


def _at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def _round_limit(value: float) -> int:
    """A credit limit rounded to whole millions, at least one million."""
    return max(1_000_000, int(value // 1_000_000 * 1_000_000))


class MasterDataSimulator:
    """Decides which reference data changes on each business day."""

    def __init__(
        self,
        seed: int,
        book_remap_day: date = DEFAULT_BOOK_REMAP_DAY,
        downgrade_day: date = DEFAULT_DOWNGRADE_DAY,
        onboard_day: date = DEFAULT_ONBOARD_DAY,
        delete_day: date = DEFAULT_DELETE_DAY,
    ):
        self._rng = random.Random(seed + 2)  # its own random stream
        self.book_remap_day = book_remap_day
        self.downgrade_day = downgrade_day
        self.onboard_day = onboard_day
        self.delete_day = delete_day
        self.fired: set[str] = set()  # scripted events that already happened
        self.next_counterparty_number = 1
        self.extra_names_used = 0
        self.downgraded_id: str | None = None

    def get_state(self) -> dict:
        return {
            "rng": encode_rng(self._rng.getstate()),
            "fired": sorted(self.fired),
            "next_counterparty_number": self.next_counterparty_number,
            "extra_names_used": self.extra_names_used,
            "downgraded_id": self.downgraded_id,
        }

    def set_state(self, state: dict) -> None:
        self._rng.setstate(decode_rng(state["rng"]))
        self.fired = set(state["fired"])
        self.next_counterparty_number = state["next_counterparty_number"]
        self.extra_names_used = state["extra_names_used"]
        self.downgraded_id = state["downgraded_id"]

    def changes_for_day(
        self, day: date, counterparties: list[dict], books: list[dict]
    ) -> list[Change]:
        """All reference data changes for this day, in the order they were committed."""
        cps = {row["counterparty_id"]: dict(row) for row in counterparties}
        changes: list[Change] = []
        touched: set[str] = set()  # counterparties already changed today

        # Scripted events
        if day == self.book_remap_day and "book_remap" not in self.fired:
            change = self._remap_book(day, books)
            if change:
                changes.append(change)
            self.fired.add("book_remap")

        if day == self.downgrade_day and "downgrade" not in self.fired:
            change = self._downgrade(day, cps)
            if change:
                changes.append(change)
                touched.add(change.row["counterparty_id"])
                self.downgraded_id = change.row["counterparty_id"]
            self.fired.add("downgrade")

        if day == self.onboard_day and "onboard" not in self.fired:
            changes.append(self._onboard(day))
            self.fired.add("onboard")

        if day == self.delete_day and "delete" not in self.fired:
            change = self._delete(day, cps)
            if change:
                changes.append(change)
                touched.add(change.row["counterparty_id"])
            self.fired.add("delete")

        # Small random changes
        for counterparty_id in sorted(cps):
            if counterparty_id in touched:
                continue
            row = dict(cps[counterparty_id])
            roll = self._rng.random()
            if roll < LIMIT_CHANGE_RATE:
                row["credit_limit_gbp"] = _round_limit(
                    row["credit_limit_gbp"] * self._rng.uniform(0.85, 1.20)
                )
                kind = "LIMIT_CHANGE"
            elif roll < LIMIT_CHANGE_RATE + RATING_CHANGE_RATE:
                position = RATING_ORDER.index(row["credit_rating"])
                step = self._rng.choice([-1, 1])
                position = min(max(position + step, 0), len(RATING_ORDER) - 1)
                row["credit_rating"] = RATING_ORDER[position]
                kind = "RATING_CHANGE"
            else:
                continue
            seconds = self._rng.randint(8 * 3600, 17 * 3600)
            when = datetime(day.year, day.month, day.day) + timedelta(seconds=seconds)
            changes.append(Change("counterparties", "U", row, when, kind))

        changes.sort(key=lambda change: change.commit_time)
        return changes

    def _remap_book(self, day: date, books: list[dict]) -> Change | None:
        """Move the last UK gas book to the EU gas desk."""
        candidates = [book for book in books if book["desk_code"] == "UKGAS"]
        if not candidates:
            return None
        row = dict(candidates[-1])
        row["desk_code"] = "EUGAS"
        return Change("books", "U", row, _at(day, *BOOK_REMAP_TIME), "BOOK_REMAP")

    def _downgrade(self, day: date, cps: dict[str, dict]) -> Change | None:
        """Downgrade the first counterparty rated A- or better by two notches."""
        safe = [
            cid
            for cid in sorted(cps)
            if RATING_ORDER.index(cps[cid]["credit_rating"]) <= RATING_ORDER.index("A-")
        ]
        pool = safe or sorted(cps)
        if not pool:
            return None
        row = dict(cps[pool[0]])
        position = min(RATING_ORDER.index(row["credit_rating"]) + 2, len(RATING_ORDER) - 1)
        row["credit_rating"] = RATING_ORDER[position]
        row["credit_limit_gbp"] = BASE_LIMIT[row["credit_rating"]]  # the limit is cut
        return Change("counterparties", "U", row, _at(day, *DOWNGRADE_TIME), "DOWNGRADE")

    def _onboard(self, day: date) -> Change:
        """A brand new counterparty."""
        number = self.next_counterparty_number
        self.next_counterparty_number += 1
        start = EXTRA_NAME_STARTS[self.extra_names_used % len(EXTRA_NAME_STARTS)]
        self.extra_names_used += 1
        country, suffix, _ = self._rng.choice(COUNTRIES)
        rating, base_limit = self._rng.choice(RATINGS)
        row = {
            "counterparty_id": f"CP-{number:05d}",
            "counterparty_name": f"{start} {self._rng.choice(NAME_SECTORS)} {suffix}",
            "country_of_risk": country,
            "credit_rating": rating,
            "credit_limit_gbp": _round_limit(base_limit * self._rng.uniform(0.75, 1.25)),
            "is_active": 1,
            "effective_from": day.isoformat(),
        }
        return Change("counterparties", "I", row, _at(day, *ONBOARD_TIME), "ONBOARD")

    def _delete(self, day: date, cps: dict[str, dict]) -> Change | None:
        """Delete a counterparty from the middle of the list. It keeps its old trades."""
        pool = [cid for cid in sorted(cps) if cid != self.downgraded_id]
        if not pool:
            return None
        target = pool[len(pool) // 2]
        return Change("counterparties", "D", dict(cps[target]), _at(day, *DELETE_TIME), "DELETE")
