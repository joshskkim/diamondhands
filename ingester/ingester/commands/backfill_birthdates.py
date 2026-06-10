"""backfill-birthdates: populate players.birth_date from the MLB Stats API.

One-off / occasional backfill (birth dates don't change). Feeds the Marcel prior's
aging curve. Idempotent: only updates rows whose birth_date is still NULL unless
--all is passed.
"""
from __future__ import annotations

import argparse

from ingester.db import get_connection
from ingester.mlb_api import fetch_people_birthdates


def cmd_backfill_birthdates(args: argparse.Namespace) -> None:
    refresh_all: bool = getattr(args, "all", False)
    conn = get_connection()
    where = "" if refresh_all else "WHERE birth_date IS NULL"
    ids = [int(r[0]) for r in conn.execute(f"SELECT id FROM players {where}").fetchall()]
    if not ids:
        print("[backfill-birthdates] No players need a birth date.")
        conn.close()
        return

    print(f"[backfill-birthdates] Fetching birth dates for {len(ids)} player(s)…")
    by_id = fetch_people_birthdates(ids)

    with conn.cursor() as cur:
        n = 0
        for pid, bd in by_id.items():
            cur.execute("UPDATE players SET birth_date = %s WHERE id = %s", (bd, pid))
            n += cur.rowcount
    conn.commit()
    conn.close()
    print(f"[backfill-birthdates] Updated {n} player(s); {len(ids) - len(by_id)} had no birthDate.")
