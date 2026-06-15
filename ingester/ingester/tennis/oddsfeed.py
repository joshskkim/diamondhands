"""The Odds API feed for tennis (sport key `tennis_atp`).

Kept separate from the MLB `odds_api.py` so the proven baseball path is untouched;
reuses only the pure odds-math helpers. Two endpoints:

  * /events  — free; upcoming matches (id, commence_time, two player names) → slate
  * /odds    — credit-billed; same events with h2h (match-winner) prices → odds

Player-name matching to tennis_players is fuzzy (accents/transliteration vary
between the data source and the books).
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import requests
from rapidfuzz import fuzz, process

from ingester.odds_api import (  # reuse pure helpers; do not touch MLB fetch/parse
    ODDS_BASE,
    ODDS_FORMAT,
    REGIONS,
    american_to_decimal,
    implied_prob,
)

TENNIS_SPORT_KEY = "tennis_atp"
_FIXTURES = Path(__file__).parent.parent / "fixtures"

GRAND_SLAMS = ("australian open", "roland garros", "french open", "wimbledon", "us open")


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace for matching."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = "".join(c if c.isalnum() or c.isspace() else " " for c in s.lower())
    return " ".join(s.split())


def build_name_index(conn) -> dict[str, str]:
    """{normalized full_name: player_id} from tennis_players."""
    rows = conn.execute("SELECT id, full_name FROM tennis_players").fetchall()
    return {normalize_name(name): pid for pid, name in rows}


def match_player(name: str, index: dict[str, str], cutoff: int = 86) -> str | None:
    """Resolve an Odds-API player name to a tennis_players id (exact, then fuzzy)."""
    key = normalize_name(name)
    if key in index:
        return index[key]
    best = process.extractOne(key, index.keys(), scorer=fuzz.token_sort_ratio,
                              score_cutoff=cutoff)
    return index[best[0]] if best else None


def is_grand_slam(title: str | None) -> bool:
    t = (title or "").lower()
    return any(g in t for g in GRAND_SLAMS)


# ── HTTP ─────────────────────────────────────────────────────────────────────

def fetch_events(api_key: str, sport_key: str = TENNIS_SPORT_KEY) -> list[dict]:
    """Upcoming events for a tennis sport key (free endpoint) — the slate source.
    NOTE: The Odds API may expose tennis as per-tournament keys (e.g.
    `tennis_atp_us_open`) rather than one `tennis_atp`; the caller can pass the
    in-season key(s). The event's sport_title still carries the tournament name."""
    resp = requests.get(
        f"{ODDS_BASE}/sports/{sport_key}/events",
        params={"apiKey": api_key, "dateFormat": "iso"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_h2h(api_key: str, sport_key: str = TENNIS_SPORT_KEY) -> list[dict]:
    """Upcoming events with match-winner (h2h) prices across US books."""
    resp = requests.get(
        f"{ODDS_BASE}/sports/{sport_key}/odds",
        params={"apiKey": api_key, "regions": REGIONS, "markets": "h2h",
                "oddsFormat": ODDS_FORMAT},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


# ── Sample fixtures (offline / no-key path) ──────────────────────────────────

def load_sample_events() -> list[dict]:
    return json.loads((_FIXTURES / "tennis_events_sample.json").read_text())


def load_sample_h2h() -> list[dict]:
    return json.loads((_FIXTURES / "tennis_h2h_sample.json").read_text())


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_h2h(event: dict) -> list[dict]:
    """Flatten one event's h2h bookmakers into rows.

    Returns dicts: player_name, bookmaker, price_american, price_decimal,
    implied_prob, last_update.
    """
    rows: list[dict] = []
    for book in event.get("bookmakers", []):
        bkey = book["key"]
        for market in book.get("markets", []):
            if market.get("key") != "h2h":
                continue
            last_update = market.get("last_update") or book.get("last_update")
            for oc in market.get("outcomes", []):
                price = oc.get("price")
                if price is None:
                    continue
                american = int(price)
                rows.append({
                    "player_name": oc.get("name"),
                    "bookmaker": bkey,
                    "price_american": american,
                    "price_decimal": round(american_to_decimal(american), 3),
                    "implied_prob": round(implied_prob(american), 4),
                    "last_update": last_update,
                })
    return rows
