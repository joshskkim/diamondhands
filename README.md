# Diamond — MLB Projection App

Stats-first MLB projection tool. Projections come first; sportsbook odds are pulled
purely to compare books for the best line and to evaluate it against the model (EV%).

## Architecture

```
/api        Spring Boot 3.3 REST API        (Java 21, port 8080)
/ingester   Data pull + projection engine   (Python 3.12, uv)
/web        UI                              (Next.js 14+, port 3000)
/db/migrations  Flyway SQL migrations
/data       Static reference data (park factors, orientations)
```

## Prerequisites

- Docker + Docker Compose
- Java 21 + Maven
- Python 3.12 + uv  (`pip install uv`)
- Node.js 20+ + npm

## Infra (Postgres + Redis)

```bash
# Start postgres:16 on :5432 and redis:7-alpine on :6379
# Flyway runs migrations automatically on first start
docker compose up -d

# Verify
docker compose ps
docker exec diamond-postgres psql -U diamond -d diamond -c "\dt"
docker exec diamond-redis redis-cli ping
```

## API

```bash
cd api
mvn spring-boot:run
# → http://localhost:8080/health  {"status":"ok"}
```

## Ingester

```bash
cd ingester
cp .env.example .env   # fill in DATABASE_URL (and optionally ODDS_API_KEY)
uv sync

# Subcommands
uv run python main.py load-static        # seed teams / stadiums from /data
uv run python main.py backfill-stats     # pull historical game logs
uv run python main.py daily-slate        # fetch today's games + probable pitchers
uv run python main.py refresh-lineups    # pull today's confirmed batting orders (idempotent)
uv run python main.py backfill-lineups --start YYYY-MM-DD --end YYYY-MM-DD  # historical lineups
uv run python main.py refresh-weather    # attach weather to today's games
uv run python main.py refresh-skills     # recompute batter_skill / pitcher_skill
uv run python main.py project            # compute batter_projections for today
uv run python main.py refresh-odds       # pull sportsbook odds (game markets + player props)
uv run python main.py refresh-odds --sample  # ...from bundled fixtures (no API key needed)
uv run python main.py daily              # run the whole daily workflow in one shot (see below)
uv run python main.py backtest --start YYYY-MM-DD --end YYYY-MM-DD          # backtesting suite
uv run python main.py smoke              # end-to-end sanity check
```

`refresh-odds` uses [The Odds API](https://the-odds-api.com). Set `ODDS_API_KEY` in
`.env` to pull live odds; without it the command is a no-op. Use `--sample` to load the
bundled fixtures so the odds UI/API are exercisable without a key or request credits.

## Web

```bash
cd web
cp .env.local.example .env.local
npm install
npm run dev   # → http://localhost:3000
```

## Typical daily workflow

```bash
# 1. Ensure infra is running
docker compose up -d

# 2. Run the full workflow in one shot:
#    slate -> weather -> skills -> lineups -> project -> odds
cd ingester && uv run python main.py daily

# 3. View in UI
cd ../web && npm run dev
```

`daily` chains the individual steps and stops on the first failure. Flags:

- `--skip-skills` — drop the ~1.5 min `refresh-skills` recompute when it isn't needed.
- `--quick` — afternoon re-projection loop only: `refresh-lineups -> project -> refresh-odds`.

The individual commands still exist if you want to run a single step:

```bash
uv run python main.py daily-slate      # ~9 AM: today's games + probables
uv run python main.py refresh-weather  # ~1 h before first pitch
uv run python main.py refresh-skills   # recompute skills if needed
uv run python main.py refresh-lineups  # confirmed lineups (re-run as they post)
uv run python main.py project          # recompute the slate's projections
uv run python main.py refresh-odds     # sportsbook odds + best lines
```

## Lineups & re-projection cadence (cron — not installed)

Confirmed lineups post ~2–3 h before first pitch and trickle in across the
afternoon. `refresh-lineups` is idempotent, and `project` recomputes the whole
slate from scratch (it clears the day's rows first), so the two can run together
on a loop. Once a game's lineup is confirmed, its batters are weighted by
batting-order PA (`PA_BY_ORDER`); until then they fall back to the projected
top-of-order proxy at a flat 4.0 PA.

Suggested cadence (US/Eastern) — **document only, do not install yet:**

```cron
# Every 30 min, noon–6 PM ET: refresh lineups then re-project today's slate.
# By first pitch all games should reflect confirmed lineups.
*/30 12-18 * * *  cd /path/to/diamond/ingester && \
    uv run python main.py refresh-lineups && \
    uv run python main.py project
```

For backtesting, seed historical lineups once with
`backfill-lineups --start … --end …` (uses the same MLB Stats API lineups
hydration, which works for past games).

