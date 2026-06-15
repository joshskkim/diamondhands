"""tennis-backfill: one-time historical load of the TML-Database ATP data into
the tennis_* tables (players, tournaments, matches, serve lines)."""
from __future__ import annotations

import argparse

from ingester.tennis.data import load_tml


def cmd_tennis_backfill(args: argparse.Namespace) -> None:
    totals = load_tml(args.start_year, args.end_year)
    print(
        f"[tennis-backfill] done: {totals['players']} players, "
        f"{totals['matches']} matches, {totals['stats']} serve lines "
        f"across {totals['years'][0]}–{totals['years'][-1]}"
    )
