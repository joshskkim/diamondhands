"""load-static: Seed teams and stadiums from the MLB Stats API + stadiums.json."""

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv

MLB_TEAMS_URL = "https://statsapi.mlb.com/api/v1/teams?sportId=1"

# stadiums.json uses Baseball Reference abbreviations; MLB Stats API uses shorter ones.
# Map JSON abbrev → API abbrev for the known mismatches.
JSON_TO_API_ABBREV: dict[str, str] = {
    "CHW": "CWS",
    "KCR": "KC",
    "SDP": "SD",
    "SFG": "SF",
    "TBR": "TB",
    "WSN": "WSH",
}

LAT_RANGE = (-90.0, 90.0)
LON_RANGE = (-180.0, 180.0)


def _fetch_teams() -> dict[str, dict]:
    """Return {api_abbreviation: {id, abbreviation, name}} from MLB Stats API."""
    resp = requests.get(MLB_TEAMS_URL, timeout=10)
    resp.raise_for_status()
    teams_by_abbrev: dict[str, dict] = {}
    for t in resp.json().get("teams", []):
        abbrev = t.get("abbreviation", "").upper()
        teams_by_abbrev[abbrev] = {
            "id": t["id"],
            "abbreviation": abbrev,
            "name": t.get("name") or t.get("teamName", abbrev),
        }
    return teams_by_abbrev


def _validate_stadium(s: dict) -> None:
    abbrev = s.get("team_abbrev", "?")
    bearing = s.get("cf_bearing_degrees")
    if bearing is None or not (0 <= bearing <= 359):
        sys.exit(f"[load-static] ERROR: {abbrev} cf_bearing_degrees={bearing!r} not in [0, 359]")
    lat = s.get("latitude")
    lon = s.get("longitude")
    if lat is None or not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]):
        sys.exit(f"[load-static] ERROR: {abbrev} latitude={lat!r} out of range")
    if lon is None or not (LON_RANGE[0] <= lon <= LON_RANGE[1]):
        sys.exit(f"[load-static] ERROR: {abbrev} longitude={lon!r} out of range")


def cmd_load_static(args: argparse.Namespace) -> None:
    """Seed teams and stadiums from the MLB Stats API and stadiums.json."""
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("[load-static] ERROR: DATABASE_URL not set in .env")

    stadiums_path = Path(args.data_dir) / "stadiums.json"
    if not stadiums_path.exists():
        sys.exit(f"[load-static] ERROR: {stadiums_path} not found")

    raw = json.loads(stadiums_path.read_text())
    stadiums = [s for s in raw if "team_abbrev" in s]

    print("[load-static] Fetching teams from MLB Stats API…")
    teams_by_api_abbrev = _fetch_teams()

    # Resolve each JSON abbreviation to an API team record, fail loudly on mismatch.
    resolved: list[tuple[dict, dict]] = []  # (stadium_json, api_team)
    unmatched: list[str] = []
    for s in stadiums:
        json_abbrev = s["team_abbrev"]
        api_abbrev = JSON_TO_API_ABBREV.get(json_abbrev, json_abbrev)
        team = teams_by_api_abbrev.get(api_abbrev)
        if team is None:
            unmatched.append(json_abbrev)
        else:
            _validate_stadium(s)
            resolved.append((s, team))

    if unmatched:
        sys.exit(
            f"[load-static] ERROR: no API match for abbreviation(s): {', '.join(unmatched)}\n"
            f"  Available API abbreviations: {sorted(teams_by_api_abbrev)}"
        )

    print(f"[load-static] Matched {len(resolved)} teams. Upserting into DB…")

    with psycopg.connect(url) as conn:
        with conn.transaction():
            # 1. Upsert teams (home_stadium_id left NULL until stadiums exist)
            for _s, team in resolved:
                conn.execute(
                    """
                    INSERT INTO teams (id, abbreviation, name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET abbreviation = EXCLUDED.abbreviation,
                            name         = EXCLUDED.name
                    """,
                    (team["id"], team["abbreviation"], team["name"]),
                )

            # 2. Upsert stadiums; use team id as stadium id (1:1 home mapping)
            for s, team in resolved:
                conn.execute(
                    """
                    INSERT INTO stadiums (
                        id, name, team_id, city,
                        latitude, longitude, altitude_feet,
                        is_dome, is_retractable, cf_bearing_degrees,
                        park_factor_hits, park_factor_hr_lhb, park_factor_hr_rhb,
                        lf_line_ft, cf_ft, rf_line_ft, lf_wall_ft, cf_wall_ft, rf_wall_ft
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET name               = EXCLUDED.name,
                            team_id            = EXCLUDED.team_id,
                            city               = EXCLUDED.city,
                            latitude           = EXCLUDED.latitude,
                            longitude          = EXCLUDED.longitude,
                            altitude_feet      = EXCLUDED.altitude_feet,
                            is_dome            = EXCLUDED.is_dome,
                            is_retractable     = EXCLUDED.is_retractable,
                            cf_bearing_degrees = EXCLUDED.cf_bearing_degrees,
                            park_factor_hits   = EXCLUDED.park_factor_hits,
                            park_factor_hr_lhb = EXCLUDED.park_factor_hr_lhb,
                            park_factor_hr_rhb = EXCLUDED.park_factor_hr_rhb,
                            lf_line_ft         = EXCLUDED.lf_line_ft,
                            cf_ft              = EXCLUDED.cf_ft,
                            rf_line_ft         = EXCLUDED.rf_line_ft,
                            lf_wall_ft         = EXCLUDED.lf_wall_ft,
                            cf_wall_ft         = EXCLUDED.cf_wall_ft,
                            rf_wall_ft         = EXCLUDED.rf_wall_ft
                    """,
                    (
                        team["id"],
                        s["stadium_name"],
                        team["id"],
                        s["city"],
                        s["latitude"],
                        s["longitude"],
                        s.get("altitude_feet"),
                        s["is_dome"],
                        s.get("is_retractable", False),
                        s["cf_bearing_degrees"],
                        s["park_factor_hits"],
                        s["park_factor_hr_lhb"],
                        s["park_factor_hr_rhb"],
                        s.get("lf_line_ft"),
                        s.get("cf_ft"),
                        s.get("rf_line_ft"),
                        s.get("lf_wall_ft"),
                        s.get("cf_wall_ft"),
                        s.get("rf_wall_ft"),
                    ),
                )

            # 3. Set home_stadium_id on each team (stadium id == team id)
            for _s, team in resolved:
                conn.execute(
                    "UPDATE teams SET home_stadium_id = %s WHERE id = %s",
                    (team["id"], team["id"]),
                )

    print(f"Loaded {len(resolved)} teams, {len(resolved)} stadiums.")
