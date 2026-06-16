"""ATP tour baselines + model constants. Tuned-from-data priors live here so the
model code stays declarative (mirrors projection/constants.py for MLB)."""
from __future__ import annotations

import os

MODEL_VERSION = "tennis-0.1.0"

# Tennismylife/TML-Database raw CSVs — a maintained, Sackmann-schema ATP dataset
# (per-year files YYYY.csv; player ids are official ATP codes). Used because the
# original JeffSackmann/tennis_atp repo is no longer public.
TML_BASE_URL = "https://raw.githubusercontent.com/Tennismylife/TML-Database/master"

# Surfaces we model. Sackmann also has "Carpet" (mostly pre-2010); we keep it as a
# bucket but it rarely appears in the recent training window.
SURFACES = ("hard", "clay", "grass")

# League-average serve points won (SPW) by surface — priors used to regress thin
# samples and to opponent-adjust returners. Refined from the loaded data, but
# these are sane starting values (servers do best on grass, worst on clay).
SURFACE_AVG_SPW: dict[str, float] = {
    "hard": 0.645,
    "clay": 0.625,
    "grass": 0.660,
    "carpet": 0.650,
    "all": 0.640,
}

# ── Elo ──────────────────────────────────────────────────────────────────────
ELO_BASE = 1500.0
# Dynamic K (Glicko-flavoured): K = ELO_K_NUM / (matches + ELO_K_SHIFT) ** ELO_K_DECAY.
# New players move fast; established players settle. (FiveThirtyEight-style.)
ELO_K_NUM = 250.0
ELO_K_SHIFT = 5.0
ELO_K_DECAY = 0.4
# Blend of surface-specific Elo with overall Elo when rating a match on a surface.
# Tuned on the walk-forward backtest: 0.3 surface / 0.7 overall minimized Brier
# (the surface ratings are thinner/noisier, so they earn a minority weight).
ELO_SURFACE_WEIGHT = 0.3
# Logistic scale for converting a rating gap into a win probability AT PREDICTION
# time. Updates use the standard 400; predictions use a wider scale (tuned on the
# backtest) because the raw 400-scale ratings are overconfident at the extremes.
ELO_PRED_SCALE = 540.0

# ── Skills (serve/return aggregation) ────────────────────────────────────────
# Recency half-life in days for time-decayed SPW/RPW.
SKILL_HALFLIFE_DAYS = 365.0
# Regression-to-surface-mean strength: prior weight in "equivalent serve points".
SKILL_PRIOR_POINTS = 200.0

# ── Refinement levers (Milestone 3) — all DEAD, kept gated off ────────────────
# Each lever adds beta * feature to the match-winner logit (feature signed so
# positive favors player_a). OFF by default (beta=0); A/B'd via
# `tennis-backtest --tune-levers`. Result (2024-01..2026-06, 4771 matches, base
# Brier 0.2183): court_speed best beta +1.75 → 0.2182 (−0.0001, noise);
# fatigue and lefty best beta 0.0 (no signal — fatigue is limited by tournament-
# start date resolution; the lefty edge is already absorbed by Elo). None beat
# the >5e-4 bar, so ALL stay 0 — like the MLB platoon / spray-hit dead levers.
# The framework + court_speed_index remain for future, better-data levers (e.g.
# age once birthdates are backfilled, or minutes-based fatigue). Don't re-test
# without a new input. Env-gated for ad-hoc experiments.
TENNIS_COURT_SPEED_BETA = float(os.environ.get("TENNIS_COURT_SPEED_BETA", "0.0"))
TENNIS_FATIGUE_BETA = float(os.environ.get("TENNIS_FATIGUE_BETA", "0.0"))
TENNIS_LEFTY_BETA = float(os.environ.get("TENNIS_LEFTY_BETA", "0.0"))

# Fatigue load window (days) — games played in the prior N days as a load proxy.
FATIGUE_WINDOW_DAYS = 14
# Typical games per match used to scale the fatigue feature to ~unit range.
FATIGUE_GAMES_SCALE = 25.0
