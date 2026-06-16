"""tennis-backfill-attributes: populate tennis_players.birth_date / backhand / hand /
height_cm from the TML-Database ATP_Database.csv.

That file's `id` column is the ATP player code (same as tennis_players.id), so we
join by code first and fall back to normalized-name. Non-destructive: only fills
columns that are currently empty."""
from __future__ import annotations

import argparse
import io
from datetime import date

import pandas as pd
import requests

from ingester.db import get_connection
from ingester.tennis.constants import TML_BASE_URL
from ingester.tennis.oddsfeed import normalize_name

ATP_DATABASE_URL = f"{TML_BASE_URL}/ATP_Database.csv"


def _parse_birthdate(value) -> date | None:
    try:
        s = str(int(value))
    except (TypeError, ValueError):
        return None
    if len(s) != 8:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _backhand(value) -> int | None:
    s = str(value).strip().upper() if value is not None else ""
    return 1 if s == "1H" else 2 if s == "2H" else None


def _hand(value) -> str | None:
    s = str(value).strip().upper() if value is not None else ""
    return s[:1] if s in ("R", "L") else None


def _int_or_none(value) -> int | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def cmd_tennis_backfill_attributes(args: argparse.Namespace) -> None:
    resp = requests.get(ATP_DATABASE_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), dtype=str)

    by_code: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for r in df.itertuples(index=False):
        attrs = {
            "birth_date": _parse_birthdate(getattr(r, "birthdate", None)),
            "backhand": _backhand(getattr(r, "backhand", None)),
            "hand": _hand(getattr(r, "hand", None)),
            "height_cm": _int_or_none(getattr(r, "height", None)),
        }
        code = (getattr(r, "id", None) or "").strip()
        if code:
            by_code[code] = attrs
        name = getattr(r, "player", None)
        if isinstance(name, str) and name.strip():
            by_name.setdefault(normalize_name(name), attrs)

    conn = get_connection()
    try:
        players = conn.execute("SELECT id, full_name FROM tennis_players").fetchall()
        updates = []
        matched = by_code_hits = 0
        for pid, full_name in players:
            attrs = by_code.get(pid) or by_name.get(normalize_name(full_name or ""))
            if attrs is None:
                continue
            matched += 1
            if pid in by_code:
                by_code_hits += 1
            updates.append((attrs["birth_date"], attrs["backhand"], attrs["hand"],
                            attrs["height_cm"], pid))

        with conn.cursor() as cur:
            cur.executemany(
                """UPDATE tennis_players SET
                     birth_date = COALESCE(birth_date, %s),
                     backhand   = COALESCE(backhand, %s),
                     hand       = COALESCE(NULLIF(hand, ''), %s),
                     height_cm  = COALESCE(height_cm, %s),
                     updated_at = NOW()
                   WHERE id = %s""",
                updates,
            )
        conn.commit()

        cov = conn.execute(
            "SELECT count(*) total, count(birth_date) dob, count(backhand) bh, "
            "count(hand) hand FROM tennis_players"
        ).fetchone()
        print(f"[tennis-backfill-attributes] matched {matched}/{len(players)} players "
              f"({by_code_hits} by code, {matched - by_code_hits} by name)")
        print(f"  coverage: birth_date {cov[1]}/{cov[0]}, backhand {cov[2]}/{cov[0]}, "
              f"hand {cov[3]}/{cov[0]}")
    finally:
        conn.close()
