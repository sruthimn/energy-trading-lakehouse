"""Command line for the simulated source system.

python -m lakehouse.generator.cli init    --dir data/source --trades-per-day 20000
python -m lakehouse.generator.cli advance --dir data/source --days 5
python -m lakehouse.generator.cli status  --dir data/source
"""

from __future__ import annotations

import argparse
from datetime import date

from lakehouse.generator.reference import DEFAULT_SEED
from lakehouse.generator.source_db import (
    DEFAULT_START_DATE,
    DEFAULT_TRADES_PER_DAY,
    SourceSystem,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lakehouse.generator", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a new source system")
    init.add_argument("--dir", required=True, help="folder to create it in")
    init.add_argument("--seed", type=int, default=DEFAULT_SEED)
    init.add_argument("--trades-per-day", type=int, default=DEFAULT_TRADES_PER_DAY)
    init.add_argument("--start-date", type=date.fromisoformat, default=DEFAULT_START_DATE)

    advance = sub.add_parser("advance", help="simulate the next business day(s)")
    advance.add_argument("--dir", required=True)
    advance.add_argument("--days", type=int, default=1)

    manifest = sub.add_parser("manifest", help="write the truth manifest (_truth/defects.json)")
    manifest.add_argument("--dir", required=True)

    status = sub.add_parser("status", help="show where the simulation is")
    status.add_argument("--dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "init":
        SourceSystem.create(
            args.dir,
            seed=args.seed,
            trades_per_day=args.trades_per_day,
            start_date=args.start_date,
        )
        print(f"Created a source system in {args.dir}.")
        print(f"The first day to simulate is {args.start_date}.")
        return 0

    system = SourceSystem(args.dir)
    if args.command == "advance":
        for result in system.advance(args.days):
            print(
                f"{result.business_date}: {result.rows} rows "
                f"({result.new_trades} new, {result.amendments} amended, "
                f"{result.cancellations} cancelled, {result.late_rows} late, "
                f"{result.master_changes} reference data changes, "
                f"{result.defects_injected} defects, {result.trades_deleted} deleted)"
            )
        print(f"Next business day to simulate: {system.next_business_date}")
        print(f"Truth manifest written to {system.write_truth_manifest()}")
        return 0

    if args.command == "manifest":
        print(f"Truth manifest written to {system.write_truth_manifest()}")
        return 0

    for key, value in system.status().items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
