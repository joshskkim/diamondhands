# Diamond Ingester

## Daily order of operations

```
# ── One-time setup (run once per environment) ──────────────────────────────
uv run python main.py load-static        # seed teams + stadiums

# ── Season backfill (run once at season start, or to catch up) ─────────────
uv run python main.py backfill-stats     # pull Statcast game logs (slow first run)
uv run python main.py refresh-skills     # aggregate batter_skill + pitcher_skill

# ── Nightly (run after midnight, before projection window) ──────────────────
uv run python main.py refresh-skills     # recompute skill aggregates with new data

# ── Each game day (run in this order) ──────────────────────────────────────
uv run python main.py daily-slate        # upsert today's games + probable pitchers
uv run python main.py refresh-weather    # attach weather forecast to each game
uv run python main.py project            # compute batter + game projections

# ── Smoke checks ────────────────────────────────────────────────────────────
uv run python main.py smoke              # DB connectivity check
uv run python main.py smoke-skills       # top-10 batters/pitchers from skill tables
uv run python main.py smoke-slate        # today's slate with weather + probables
uv run python main.py smoke-project      # run project + verify row counts
```

---

## load-static

Seeds the `teams` and `stadiums` tables from two sources:

1. **MLB Stats API** (`statsapi.mlb.com`) — provides authoritative MLBAM team IDs, abbreviations, and full names.
2. **`/data/stadiums.json`** — static park factors (Statcast 3-yr rolling) and stadium metadata for all 30 ballparks.

```bash
uv run python main.py load-static
# Optional override: --data-dir /path/to/data
```

Idempotent (safe to re-run). Fails loudly if any team abbreviation cannot be matched.

---

## backfill-stats

Pulls pitch-level Statcast data via pybaseball for the full season, aggregates to
game-level batter and pitcher stats, and upserts into `player_game_stats` and `pitcher_skill`.

```bash
uv run python main.py backfill-stats [--season 2025]
```

First run is slow (~30 min). pybaseball caches weekly chunks in `~/.pybaseball/`;
subsequent runs reuse the cache and are fast.

---

## refresh-skills

Re-aggregates `batter_skill` and `pitcher_skill` from `player_game_stats`
(and the pybaseball disk cache for pitcher handedness splits).

```bash
uv run python main.py refresh-skills [--season 2025]
```

Run nightly. Fast (~90 s) after the initial backfill because it reads cached CSVs.

---

## daily-slate

Fetches today's schedule from the MLB Stats API (hydrated with `probablePitcher`)
and upserts into the `games` table.

```bash
uv run python main.py daily-slate
```

- Handles doubleheaders (two games same date, same teams — distinct `game_pk`).
- Probable pitchers may be `NULL` up to ~24 h before first pitch; the projector
  skips games with missing probables and logs a warning.
- Safe to re-run (upsert on `games.id`).

---

## refresh-weather

Fetches hourly weather from [Open-Meteo](https://open-meteo.com/) for each
`Scheduled` game today with a start time within the next 24 h.

```bash
uv run python main.py refresh-weather
```

- **Open-Meteo is free for non-commercial use — no API key required.**
- Fully enclosed domed stadiums (`is_dome=true`, `is_retractable=false`) receive
  sentinel values (72 °F, 0 mph, 0°) instead of an API call.
- `wind_direction_degrees` is the **meteorological "from" direction**: 0° = wind
  blowing from North (southward), 90° = from East (westward), etc.
  Compare against `stadiums.cf_bearing_degrees` in the projector to determine
  whether wind carries toward or away from the plate.

---

## project

Computes `batter_projections` and `game_projections` for the slate. See
[`PROJECTION_MODEL.md`](PROJECTION_MODEL.md) for the full algorithm.

```bash
uv run python main.py project
uv run python main.py project --date 2025-05-28
```

Requires `daily-slate`, `refresh-weather`, and `refresh-skills` for the same date.

---

## smoke-project

Integration check: runs `project`, then verifies `batter_projections` row count
matches the v1 lineup proxy (top-13 hitters per team with `batter_skill`) on
each projected game.

```bash
uv run python main.py smoke-project
```

---

## smoke-slate

Prints today's slate for a quick visual sanity check.

```bash
uv run python main.py smoke-slate
```
