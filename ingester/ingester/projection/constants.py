"""League baselines and projection tuning parameters (2025 defaults).

All rates are per plate appearance unless noted. Coefficients match the v1
projection spec; change here when backtesting suggests new values.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# League-average reference (2025 MLB approximations)
# ---------------------------------------------------------------------------

LEAGUE_XWOBA: float = 0.318
LEAGUE_WOBA: float = 0.318
LEAGUE_HIT_PER_PA: float = 0.225
LEAGUE_HR_PER_PA: float = 0.030
LEAGUE_K_PER_PA: float = 0.225
LEAGUE_ISO: float = 0.155

# ---------------------------------------------------------------------------
# Batter skill blending (L30 vs season)
# ---------------------------------------------------------------------------

# weight_l30 = min(pa_l30 / PA_L30_FULL_WEIGHT, PA_L30_BLEND_CAP)
PA_L30_FULL_WEIGHT: int = 150
PA_L30_BLEND_CAP: float = 0.6

# refresh-skills: season totals require this many PA; below → league-average skill.
MIN_PA_BATTER_SEASON: int = 150

# L30 window in refresh-skills: below this PA, L30 columns are intentionally NULL.
L30_MIN_PA: int = 30

# ---------------------------------------------------------------------------
# Pitcher handedness splits
# ---------------------------------------------------------------------------

# Below this BF vs a hand, fall back to overall (both hands averaged).
MIN_BF_PITCHER_HANDEDNESS: int = 50

# ---------------------------------------------------------------------------
# Lineup / expected PA (v1 approximations)
# ---------------------------------------------------------------------------

# Stand-in for confirmed lineups: top N hitters by PA in last 30 days.
LINEUP_SIZE_HITTERS: int = 13

# Starters used for team run aggregation (9 lineup spots).
LINEUP_STARTERS: int = 9

# Fixed team PA budget for v1 (actual weights sum to ~37; we use flat PA below).
TEAM_PA_ESTIMATE: float = 38.0

# Order-weighted PA when lineup order is known (v2). Sum ≈ 37.
LINEUP_PA_WEIGHTS: tuple[float, ...] = (
    4.6,
    4.4,
    4.3,
    4.2,
    4.1,
    4.0,
    3.9,
    3.8,
    3.7,
)

# v1: unknown batting order → same expected PA for every projected starter.
EXPECTED_PA_PER_STARTER: float = 4.0

# ---------------------------------------------------------------------------
# Switch hitter rule (apply in pitcher_adj and park_adj)
# ---------------------------------------------------------------------------
# Treat switch hitters as batting from the side opposite the pitcher's throws:
# vs RHP → bat left (L); vs LHP → bat right (R). Same rule for park HR factor.

# ---------------------------------------------------------------------------
# Pull direction (degrees from north, clockwise)
# ---------------------------------------------------------------------------

# Offset from CF bearing toward the batter's pull field.
PULL_BEARING_OFFSET_DEG: float = 35.0

# ---------------------------------------------------------------------------
# Weather adjustment coefficients
# ---------------------------------------------------------------------------

WEATHER_TEMP_BASELINE_F: float = 70.0

# HR rate ~0.5% per °F above/below baseline.
TEMP_HR_COEFF_PER_F: float = 0.005
TEMP_HR_CLAMP: tuple[float, float] = (0.85, 1.20)

# Slight hit-rate temperature effect at v1.
TEMP_HIT_COEFF_PER_F: float = 0.001
TEMP_HIT_CLAMP: tuple[float, float] = (0.95, 1.05)

# HR rate ~2.5% per mph of pull-side tailwind component.
WIND_HR_COEFF_PER_MPH: float = 0.025
WIND_HR_CLAMP: tuple[float, float] = (0.70, 1.40)

# Dome / closed roof: no weather effect on hit or HR.
DOME_WEATHER_ADJ: float = 1.0

# ---------------------------------------------------------------------------
# Per-PA rate and derived-count clamps
# ---------------------------------------------------------------------------

# Hard clamps on final adjusted per-PA rates (after all multipliers).
ADJUSTED_HIT_PER_PA_CLAMP: tuple[float, float] = (0.10, 0.45)
ADJUSTED_HR_PER_PA_CLAMP: tuple[float, float] = (0.001, 0.10)
ADJUSTED_K_PER_PA_CLAMP: tuple[float, float] = (0.05, 0.45)

# Pitcher matchup multipliers (raw rate / league rate).
PITCHER_MULT_HIT_CLAMP: tuple[float, float] = (0.75, 1.30)
PITCHER_MULT_HR_CLAMP: tuple[float, float] = (0.60, 1.50)
PITCHER_MULT_K_CLAMP: tuple[float, float] = (0.70, 1.40)

# expected_total_bases: avg bases per hit ≈ 1 + iso_blend * 3
AVG_BASES_PER_HIT_ISO_MULT: float = 3.0
AVG_BASES_PER_HIT_CLAMP: tuple[float, float] = (1.0, 2.5)

# ---------------------------------------------------------------------------
# Team run expectation (v1 Pythagorean-ish proxy; weak — see PROJECTION_MODEL.md)
# ---------------------------------------------------------------------------

LEAGUE_RUNS_PER_GAME_BASE: float = 4.5
TEAM_RUNS_XWOBA_EXPONENT: float = 1.8

# ---------------------------------------------------------------------------
# Probability output
# ---------------------------------------------------------------------------

PROB_DECIMAL_PLACES: int = 4
