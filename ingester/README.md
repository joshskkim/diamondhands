# Diamond Ingester

## load-static

Seeds the `teams` and `stadiums` tables from two sources:

1. **MLB Stats API** (`statsapi.mlb.com`) — provides authoritative MLBAM team IDs, abbreviations, and full names.
2. **`/data/stadiums.json`** — static park factors (Statcast 3-yr rolling) and stadium metadata for all 30 ballparks.

```bash
uv run python main.py load-static
# Optional override: --data-dir /path/to/data
```

The command is idempotent (safe to re-run) and fails loudly if any team abbreviation cannot be matched.
