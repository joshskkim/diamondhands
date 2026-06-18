"""The Odds API helpers — game markets, player props, and odds math.

Wire format reference (the-odds-api.com v4):
  GET /sports/baseball_mlb/odds?regions=us&markets=h2h,spreads,totals&oddsFormat=american
    -> [ { id, commence_time, home_team, away_team, bookmakers: [
             { key, title, last_update, markets: [
                 { key, last_update, outcomes: [ {name, price, point?} ] } ] } ] } ]
  GET /sports/baseball_mlb/events/{event_id}/odds?markets=batter_hits,...&oddsFormat=american
    -> same shape, but prop outcomes carry a `description` (player full name) and
       `name` is the side (Over / Under).

Canonical market keys never leak past the ingester (see GAME_MARKETS / PROP_MARKETS).
Without ODDS_API_KEY set, callers should no-op; `--sample` reads committed fixtures so
the whole pipeline is testable without spending request credits.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

ODDS_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "baseball_mlb"
REGIONS = "us"
ODDS_FORMAT = "american"

# Provider game-market key -> canonical market key.
# Featured markets are the only game markets the slate-wide /odds endpoint serves.
FEATURED_MARKETS = {
    "h2h": "moneyline",
    "spreads": "run_line",
    "totals": "total",
}

# Period (first-N-innings) game markets are only available on the per-EVENT odds
# endpoint (like player props), so they are fetched per event alongside the props.
# F5 is the period our starter-driven sim predicts best; total_f1 over 0.5 == YRFI.
PERIOD_MARKETS = {
    "h2h_1st_5_innings": "moneyline_f5",
    "spreads_1st_5_innings": "run_line_f5",
    "totals_1st_5_innings": "total_f5",
    "totals_1st_1_innings": "total_f1",
}

# Full canonical map used when parsing any game-markets payload (featured or period).
GAME_MARKETS = {**FEATURED_MARKETS, **PERIOD_MARKETS}

# Canonical game markets that are over/under (vs. home/away team) markets.
TOTAL_MARKETS = {"total", "total_f5", "total_f1"}
# Canonical game markets that carry a spread point on each team side.
RUN_LINE_MARKETS = {"run_line", "run_line_f5"}

# Provider player-prop key -> canonical market key.
PROP_MARKETS = {
    "batter_hits": "hit",
    "batter_home_runs": "hr",
    "batter_walks": "bb",
    "pitcher_strikeouts": "pitcher_k",
    "pitcher_outs": "pitcher_outs",
}

_FIXTURES = Path(__file__).parent / "fixtures"


# ── Odds math ────────────────────────────────────────────────────────────────

def american_to_decimal(american: int) -> float:
    """Convert American odds to decimal payout multiplier (stake included)."""
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def implied_prob(american: int) -> float:
    """Implied win probability from American odds (includes the book's vig)."""
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


# ── HTTP ─────────────────────────────────────────────────────────────────────

def fetch_game_odds(api_key: str) -> list[dict]:
    """Upcoming MLB events with moneyline / run line / total prices across US books.

    The slate-wide endpoint only serves the featured markets; period (F5/F1) markets
    come from the per-event endpoint (see fetch_event_props).
    """
    resp = requests.get(
        f"{ODDS_BASE}/sports/{SPORT_KEY}/odds",
        params={
            "apiKey": api_key,
            "regions": REGIONS,
            "markets": ",".join(FEATURED_MARKETS),
            "oddsFormat": ODDS_FORMAT,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_event_props(api_key: str, event_id: str) -> dict:
    """Per-event odds for one event (separate, credit-billed endpoint).

    Returns player props AND the period (F5/F1) game markets in a single call — both
    are only available on this endpoint. parse_prop_markets / parse_game_markets pull
    the two kinds out of the returned event.
    """
    resp = requests.get(
        f"{ODDS_BASE}/sports/{SPORT_KEY}/events/{event_id}/odds",
        params={
            "apiKey": api_key,
            "regions": REGIONS,
            "markets": ",".join([*PROP_MARKETS, *PERIOD_MARKETS]),
            "oddsFormat": ODDS_FORMAT,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


# ── Sample fixtures (offline / no-key path) ──────────────────────────────────

def load_sample_game_odds() -> list[dict]:
    return json.loads((_FIXTURES / "odds_game_sample.json").read_text())


def load_sample_props() -> dict[str, dict]:
    """Return {event_id: props_event} so the command can look props up per event."""
    return json.loads((_FIXTURES / "odds_props_sample.json").read_text())


# ── Parsing: provider event -> normalized rows ────────────────────────────────

def parse_game_markets(event: dict) -> list[dict]:
    """Flatten one event's bookmakers into normalized game-odds rows.

    Returns dicts with: bookmaker, market, side, line, price_american, last_update.
    side is home/away (h2h, spreads keyed off the event's home/away team) or
    over/under (totals).
    """
    home = event["home_team"]
    away = event["away_team"]
    rows: list[dict] = []
    for book in event.get("bookmakers", []):
        bkey = book["key"]
        for market in book.get("markets", []):
            canonical = GAME_MARKETS.get(market["key"])
            if canonical is None:
                continue
            last_update = market.get("last_update") or book.get("last_update")
            for oc in market.get("outcomes", []):
                name = oc.get("name")
                point = oc.get("point")
                if canonical in TOTAL_MARKETS:
                    side = name.lower()  # "Over"/"Under"
                    if side not in ("over", "under"):
                        continue
                    line = point
                else:  # moneyline / run_line keyed by team (full-game or F5)
                    if name == home:
                        side = "home"
                    elif name == away:
                        side = "away"
                    else:
                        continue
                    line = point if canonical in RUN_LINE_MARKETS else None
                rows.append(
                    {
                        "bookmaker": bkey,
                        "market": canonical,
                        "side": side,
                        "line": line,
                        "price_american": int(oc["price"]),
                        "last_update": last_update,
                    }
                )
    return rows


def parse_prop_markets(event: dict) -> list[dict]:
    """Flatten one event's prop bookmakers into normalized rows.

    Returns dicts with: player_name, market, side, line, price_american,
    bookmaker, last_update.
    """
    rows: list[dict] = []
    for book in event.get("bookmakers", []):
        bkey = book["key"]
        for market in book.get("markets", []):
            canonical = PROP_MARKETS.get(market["key"])
            if canonical is None:
                continue
            last_update = market.get("last_update") or book.get("last_update")
            for oc in market.get("outcomes", []):
                player_name = oc.get("description")
                side = (oc.get("name") or "").lower()
                if not player_name or side not in ("over", "under"):
                    continue
                rows.append(
                    {
                        "player_name": player_name,
                        "market": canonical,
                        "side": side,
                        "line": oc.get("point"),
                        "price_american": int(oc["price"]),
                        "bookmaker": bkey,
                        "last_update": last_update,
                    }
                )
    return rows
