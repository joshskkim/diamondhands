"""Fetch batter projections from FanGraphs' public projections API.

FanGraphs serves every projection system as JSON from one endpoint, no auth:
    https://www.fangraphs.com/api/projections?type=<system>&stats=bat&pos=all&...
The response already carries our model inputs — wOBA, ISO, K%, PA — keyed to
xMLBAMID (= players.id), so it drops straight into ingest_prior_frame.

The endpoint sits behind Cloudflare, which 403s plain requests/urllib regardless
of headers. curl_cffi's TLS/JA3 browser impersonation passes the passive check
(no headless browser needed), which is why it's used here instead of `requests`.

System codes (the API `type=` param):
    steamer  — Steamer (preseason, updated in-season)
    thebatx  — THE BAT X (Statcast-driven, power/HR-focused)
    thebat   — THE BAT (no Statcast; THE BAT X's sibling)
    atc      — ATC (a weighted blend of public systems)
    fangraphsdc — Depth Charts (FanGraphs' house blend; best playing-time forecasts)
    zips     — ZiPS, full season (comps + aging; preseason-style true-talent input)
    oopsy    — OOPSY (methodologically independent system)

Note: `zips` is the full-season set, NOT `rzips` (rest-of-season). RoS updates in-season
and is the wrong variant for a true-talent prior (it leaks when fit/scored same-season).
ATC and Depth Charts are aggregates of the base systems, so they partly double-count them.
"""
from __future__ import annotations

import pandas as pd

SYSTEMS = ("steamer", "thebatx", "thebat", "atc", "fangraphsdc", "zips", "oopsy")

_BASE_URL = "https://www.fangraphs.com/api/projections"


def fetch_projection(system: str, stats: str = "bat") -> pd.DataFrame:
    """Return a FanGraphs projection set as a DataFrame (one row per player).

    Columns are passed through verbatim (PlayerName, xMLBAMID, wOBA, ISO, K%, PA,
    …) so ingest_prior_frame's case-insensitive header matching handles them.
    """
    # Imported lazily so the rest of the ingester runs without curl_cffi present.
    from curl_cffi import requests as creq

    params = {
        "type": system,
        "stats": stats,
        "pos": "all",
        "team": "0",
        "players": "0",
        "lg": "all",
    }
    resp = creq.get(_BASE_URL, params=params, impersonate="chrome", timeout=60)
    if "json" not in resp.headers.get("content-type", ""):
        raise RuntimeError(
            f"[fangraphs] '{system}' returned non-JSON (status {resp.status_code}); "
            "Cloudflare may be challenging this client."
        )
    data = resp.json()
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"[fangraphs] '{system}' returned no rows.")
    return pd.DataFrame(data)
