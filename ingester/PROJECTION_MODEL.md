# Projection model (v1)

The ingester `project` command fills `batter_projections` and `game_projections` for each game on a given slate. This document describes the algorithm, assumptions, and known weaknesses.

## Pipeline

For each game with a stadium, both probable pitchers, and weather (outdoor or dome sentinel):

1. **Lineup proxy** — Top 13 non-pitchers per team by PA in the last 30 days (`player_game_stats`). Not a confirmed lineup.
2. **Skill blend** — `weight_l30 = min(pa_l30 / 150, 0.6)` (L30 never &gt;60% of blend). NULL `pa_l30` → season only. `refresh-skills` L30 window is last 30 days ending today; `pa_l30 &lt; 30` → L30 columns NULL.
3. **Base rates (per PA)** — Hit ∝ xwOBA vs league; **HR ∝ ISO vs league** (not xwOBA); K = blended K%.
4. **Pitcher adjustment** — Rate / league rate, clamped (hit 0.75–1.30, HR 0.60–1.50, K 0.70–1.40).
5. **Park adjustment** — `park_factor_hits`; HR factor LHB/RHB by effective batter hand.
6. **Weather adjustment** — Dome + non-retractable: 1.0. Else temperature (HR and slight hit) and pull-direction wind component for HR. See `weather_adj.py`.
7. **Adjusted rates** — Multiply factors; hard clamp hit [0.10, 0.45], HR [0.001, 0.10], K [0.05, 0.45]. K ignores park/weather at v1.
8. **Expected PA** — Flat 4.0 per starter (lineup order unknown).
9. **Probabilities** — Independent Bernoulli: P(≥1 hit/HR/K); P(≥2 hits) via binomial CDF. Rounded to 4 decimals.
10. **Expected counts** — `expected_hits`, `expected_total_bases` (avg bases per hit ≈ `1 + iso_blend × 3`, clamped).
11. **Team runs** — Mean xwOBA of first 9 projected starters; `4.5 × (team_xwoba / league_xwoba)^1.8 × park_hits × mean(weather_hit_adj)`.
12. **Persist** — Upsert projections; set `games.projected_at`.

Code layout: `ingester/projection/` (`constants`, `weather_adj`, `park_adj`, `pitcher_adj`, `batter_model`, `runner`).

## Assumptions

- **Switch hitters** always bat opposite the pitcher’s throwing hand (park HR, pitcher split, wind pull bearing).
- **Retractable roofs** — v1 assumes closed when `is_dome` (no open/closed flag on `games`).
- **Wind** — Open-Meteo “from” direction; converted to blow-toward before pull-side component.
- **Missing data** — Skip game (no probables, outdoor weather, or pitcher_skill); skip individual batters without `batter_skill`.

## Known weaknesses (v2+)

| Area | v1 limitation |
|------|----------------|
| Lineups | Top-13-by-PA proxy, not confirmed order |
| Expected PA | Flat 4.0; weights exist in `LINEUP_PA_WEIGHTS` but unused |
| Team runs | Pythagorean-ish proxy; no base-out / RE24 matrix |
| Pitcher props | Not modeled |
| Backtesting | No harness yet — avoid ad-hoc fudge factors until backtested |
| Weather | Wind affects HR only; retractable open state not tracked |

## Verification

```bash
uv run python main.py smoke-project [--date YYYY-MM-DD]
```

Runs `project`, then checks that `batter_projections` row count equals projectable slate hitters (lineup proxy ∩ `batter_skill`) for each projected game.

## League defaults (2025)

Centralized in `projection/constants.py` (xwOBA 0.318, hit/PA 0.225, HR/PA 0.030, K/PA 0.225, ISO 0.155).
