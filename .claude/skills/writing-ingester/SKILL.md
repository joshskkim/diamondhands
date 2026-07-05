---
name: writing-ingester
description: Conventions for the Python data pipeline and projection engine (ingester/). Read before adding or editing commands, projection code, API clients, or tests under ingester/.
---

# Writing ingester/ code

Stack: Python 3.12, uv, argparse CLI, raw psycopg against Postgres, `unittest`-style tests run
via pytest.

## CLI commands

New command = `cmd_*(args: argparse.Namespace)` in `ingester/commands/<name>.py`, wired into
`build_parser()` in `main.py`. Orchestration chains live in `commands/daily.py` — preserve
existing step order when inserting.

## Database

- Connections via the helpers in `ingester/db.py` — the `connection()` context manager
  (commit/rollback/close) and the generic `upsert()` builder (being introduced in cleanup; if
  they exist, use them — do NOT hand-roll another try/commit/rollback block or
  `INSERT … ON CONFLICT` string).
- **Never hardcode a season default** (a hardcoded `--season 2025` silently aggregated the wrong
  year in 2026). Derive season from the date being processed.
- Queries on `pitcher_arsenal` / `batter_pitch_type_stats` MUST filter season — multiple seasons
  share an `as_of_date` and rows fan out.

## External APIs

HTTP fetches go through the shared retry client (`ingester/http.py`, being lifted from
`weather.py`'s `_get_with_retry`) — no bare `requests.get(...).raise_for_status()` in new code.

## Projection engine

- Frozen dataclasses (`@dataclass(frozen=True)`), `from __future__ import annotations`, PEP 604
  unions — match the existing style.
- Tunables/levers live in `projection/constants.py`, env-overridable via `DIAMOND_*`. The dormant
  levers (platoon, chase-K, whiff-K, HR-barrel, park-hit-geo) are **deliberate** A/B switches kept
  OFF — don't remove them, don't turn them on without a fresh backtest.
- Anything touching projection math must keep the backtest path equivalent: run the same date
  before/after and diff the persisted rows.

## Done =

`uv run pytest -q` green (the full suite — it needs no DB and runs in seconds) and
`uv run ruff check .` clean. Tests use `unittest` + `mock` with the `_FakeConn` pattern
(see `tests/test_boxscore_lineups.py`).
