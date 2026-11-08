"""Deliberate data problems, injected into the source system.

Real source systems are not clean. This module spoils a few rows on purpose, and
records exactly which ones, so tests can prove the pipeline finds every one.

Defects injected here
---------------------
D04  a mandatory field is empty (volume, unit, book, commodity or delivery start)
D05  the delivery period ends before it starts
D14  a trade points to a counterparty that does not exist (an orphan)
D17  a trade row is physically deleted from the source, which a watermark cannot see

Only the table in the database is spoiled. The simulator's own picture of the
trade stays clean, so a later amendment of the same trade is a good row.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

# The source system is lenient about these columns. A real system often is.
NULLABLE_COLUMNS = ["book_id", "commodity_code", "delivery_start", "volume", "unit"]

DEFAULT_NULL_RATE = 0.0005  # share of rows with an empty mandatory field (D04)
DEFAULT_BAD_RANGE_RATE = 0.0002  # share of rows with the end before the start (D05)
DEFAULT_ORPHAN_RATE = 0.0002  # share of new trades with an unknown counterparty (D14)
DEFAULT_HARD_DELETE_DAY = date(2026, 4, 2)
DEFAULT_HARD_DELETE_COUNT = 5  # trades deleted on that day (D17)

# Counterparty ids start with CP-0, so any id starting CP-9 can never be real.
ORPHAN_PREFIX = "CP-9"


@dataclass(frozen=True)
class Injection:
    """One spoiled row."""

    kind: str  # NULL_FIELD, BAD_DELIVERY_RANGE or ORPHAN_COUNTERPARTY
    trade_id: str
    trade_version: int
    detail: str  # which column, or which fake counterparty id


class DefectInjector:
    """Spoils a few rows of each day's trades, using its own random stream."""

    def __init__(
        self,
        seed: int,
        null_rate: float = DEFAULT_NULL_RATE,
        bad_range_rate: float = DEFAULT_BAD_RANGE_RATE,
        orphan_rate: float = DEFAULT_ORPHAN_RATE,
        hard_delete_day: date = DEFAULT_HARD_DELETE_DAY,
        hard_delete_count: int = DEFAULT_HARD_DELETE_COUNT,
    ):
        self._rng = random.Random(seed + 3)
        self.null_rate = null_rate
        self.bad_range_rate = bad_range_rate
        self.orphan_rate = orphan_rate
        self.hard_delete_day = hard_delete_day
        self.hard_delete_count = hard_delete_count
        self.hard_delete_done = False

    # ------------------------------------------------------------------
    def get_state(self) -> dict:
        version, internal, gauss = self._rng.getstate()
        return {
            "rng": [version, list(internal), gauss],
            "hard_delete_done": self.hard_delete_done,
        }

    def set_state(self, state: dict) -> None:
        version, internal, gauss = state["rng"]
        self._rng.setstate((version, tuple(internal), gauss))
        self.hard_delete_done = state["hard_delete_done"]

    # ------------------------------------------------------------------
    def spoil(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, list[Injection]]:
        """Return a copy of the day's trades with a few rows spoiled, and the list of them."""
        frame = frame.copy()
        injections: list[Injection] = []
        columns = list(frame.columns)
        null_threshold = self.null_rate
        range_threshold = null_threshold + self.bad_range_rate
        orphan_threshold = range_threshold + self.orphan_rate

        for position in range(len(frame)):
            roll = self._rng.random()  # one roll per row, so a row gets at most one defect
            if roll >= orphan_threshold:
                continue
            trade_id = frame.iat[position, columns.index("trade_id")]
            version = int(frame.iat[position, columns.index("trade_version")])

            if roll < null_threshold:
                column = self._rng.choice(NULLABLE_COLUMNS)
                frame.iat[position, columns.index(column)] = None
                injections.append(Injection("NULL_FIELD", trade_id, version, column))
            elif roll < range_threshold:
                start = frame.iat[position, columns.index("delivery_start")]
                frame.iat[position, columns.index("delivery_end")] = start - timedelta(days=1)
                injections.append(Injection("BAD_DELIVERY_RANGE", trade_id, version, ""))
            elif version == 1:  # an orphan only makes sense for a brand new trade
                fake = f"{ORPHAN_PREFIX}{self._rng.randint(0, 9999):04d}"
                frame.iat[position, columns.index("counterparty_id")] = fake
                injections.append(Injection("ORPHAN_COUNTERPARTY", trade_id, version, fake))
        return frame, injections

    # ------------------------------------------------------------------
    def is_hard_delete_day(self, day: date) -> bool:
        return (
            self.hard_delete_count > 0 and day == self.hard_delete_day and not self.hard_delete_done
        )

    def pick_trades_to_delete(self, candidates: list[str]) -> list[str]:
        """Choose which trades to delete from a sorted list of safe candidates."""
        self.hard_delete_done = True
        count = min(self.hard_delete_count, len(candidates))
        return sorted(self._rng.sample(candidates, count))
