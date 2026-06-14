"""League baselines and projection tuning parameters (2025 defaults).

All rates are per plate appearance unless noted. Coefficients match the v1
projection spec; change here when backtesting suggests new values.
Bump MODEL_VERSION whenever the projection logic or constants change.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Model identity (increment on any constants or logic change)
# ---------------------------------------------------------------------------

# Projection model identity. v2.1.0: the pitch-mix matchup drives the batter's
# hit/K/HR rates (replacing the season blend). Note the full-season backtest found
# this Brier-neutral-to-slightly-negative vs v2.0.0 — kept for an explainable
# projection that matches the matchup surfaced in the UI (user decision).
# v2.4.0: in-season rates regress toward a Marcel-style multi-year true-talent
# prior (see prior.py) instead of the flat league mean.
# v2.5.0: park HR factor is personalized per batter from spray + EV/LA carry vs
# the park's fence geometry (see park_adj.personalized_park_hr_mult).
# v2.6.0: weather HR effect is a physical fly-ball carry-vs-fence model (carry_delta_ft
# → weather_carry_hr_mult), replacing the flat density×wind scalar.
# v2.6.1: Marcel prior regresses each metric by its own constant (K light, ISO heavy).
# v2.7.0: thin ISO histories regress toward a bat-speed-implied ISO anchor (Statcast
# bat tracking) instead of the flat league mean.
MODEL_VERSION: str = "v2.10.0"

# ---------------------------------------------------------------------------
# League-average reference (2025 MLB approximations)
# ---------------------------------------------------------------------------

LEAGUE_XWOBA: float = 0.318
LEAGUE_WOBA: float = 0.318
LEAGUE_HIT_PER_PA: float = 0.225
LEAGUE_HR_PER_PA: float = 0.030
LEAGUE_K_PER_PA: float = 0.225
LEAGUE_BB_PER_PA: float = 0.085
LEAGUE_ISO: float = 0.155
LEAGUE_BARREL_RATE: float = 0.078  # mean barrels / batted-ball-in-play (population)

# ---------------------------------------------------------------------------
# Empirical-Bayes regression to the mean (v1.6.0)
# ---------------------------------------------------------------------------
# refresh-skills regresses every player's raw rates toward the league mean by
# sample size: weight_player = n / (n + K). Replaces the old hard league-average
# fallback for sub-threshold players (which crushed prediction variance — 50% of
# snapshots were sitting at exactly LEAGUE_XWOBA). Larger K = more regression.

# "Phantom" league-average PAs added to each batter's season sample.
REGRESSION_K_PA: int = 200
# Smaller K for the 30-day window (recent form should move faster).
REGRESSION_K_PA_L30: int = 80
# Pitcher batters-faced regression. BF accrues ~1:1 with PA, so no scaling.
REGRESSION_K_BF: int = 100

# ---------------------------------------------------------------------------
# Marcel-style multi-year true-talent prior (v2.4.0)
# ---------------------------------------------------------------------------
# refresh-priors builds a per-player projected baseline from the prior three
# seasons; refresh-skills then regresses each player's in-season rates toward
# THAT prior (by season PA, via REGRESSION_K_PA) instead of the flat league
# mean. A thin in-season sample therefore reverts to the player's established
# skill, not the league average. See ingester/projection/prior.py.
#
# Recency weights for (target-1, target-2, target-3) — classic Marcel 5/4/3.
MARCEL_SEASON_WEIGHTS: tuple[int, int, int] = (5, 4, 3)
# Phantom league-average weighted-PA mixed into the prior, so a thin multi-year
# record reverts to league. Per-metric (v2.6.1): an out-of-sample fit (2023/24
# priors → actual 2025, n=353) showed a single constant is wrong — a metric should
# be regressed in proportion to how SLOWLY it stabilizes. K% settles fast (trust the
# player → light regression), ISO is noisy (heavy regression), xwOBA in between.
MARCEL_REGRESSION_PA_XWOBA: int = 1500
MARCEL_REGRESSION_PA_K: int = 800
MARCEL_REGRESSION_PA_ISO: int = 1800

# ---------------------------------------------------------------------------
# Bat-speed-implied ISO anchor (v2.7.0)
# ---------------------------------------------------------------------------
# Thin ISO histories regress toward a bat-speed-implied ISO instead of the flat
# league mean (prior.bat_speed_iso_anchor). Out-of-sample gate (2024 tracking →
# 2025 ISO, n=324, 5-fold CV): pooled effect nil — bat speed is redundant with a
# full Marcel history (corr .61) — but the thin-history half improved ISO MAE by
# 4.0% (.03361 → .03228), and the anchor architecture confines the influence to
# exactly that cohort (evidence-rich PA swamps the 1800 phantom). Coefficients
# from the standalone anchor fit: iso ≈ league + .0187·bs_z + .0082·fast_z
# (standalone corr .496); feature moments from the 2024 fit population.
BAT_SPEED_ISO_PER_Z: float = 0.0187
FAST_SWING_ISO_PER_Z: float = 0.0082
BAT_SPEED_MEAN: float = 69.6
BAT_SPEED_SD: float = 2.89
FAST_SWING_MEAN: float = 0.213
FAST_SWING_SD: float = 0.170

# Whiff-implied K anchor (v2.8) — the K-rate analogue of the bat-speed ISO anchor.
# A batter's pitch-level whiff rate carries contact skill that PA-level K rate does
# not fully capture. Out-of-sample (2024 whiff -> 2025 K, n=322): adding whiff to a
# regressed prior cut K-rate MAE 1.5% in free regression and -13.2% when wired as
# the regression target for the K prior (no refit) — and unlike bat speed the gain
# is NOT confined to thin histories (deep 300+ PA: -17.5%), because league-shrinking
# a high-whiff hitter's K toward the mean over-corrects exactly where whiff is most
# informative. Standalone anchor fit: K ≈ league_k + .0401·whiff_z; whiff moments
# from the 2024 qualified population. Self-limiting: own weighted PA swamps the
# 800 phantom for evidence-rich batters.
WHIFF_K_PER_Z: float = float(os.environ.get("DIAMOND_WHIFF_K_PER_Z", "0.0401"))
WHIFF_MEAN: float = 0.2262
WHIFF_SD: float = 0.0594

# Barrel-rate HR basis (v2.9). The HR rate was derived purely from ISO, which
# conflates doubles/triples power with true HR power. Barrel rate is the canonical
# HR predictor. Out-of-sample (2024 barrel -> 2025 HR/PA, n=315): barrel beats ISO
# (corr .593 -> .643) and the multiplicative blend that the model ships,
# hr_scale = (1-w)*iso_scale + w*barrel_scale, minimises OOS HR-rate MAE at
# w≈0.6-0.7 (-14% vs ISO-only). w=0.6 keeps ISO's independent gap-power signal
# (barrel-only at w=1.0 regresses). Barrel is fed as a PRIOR-season true-talent
# input (leak-free, like the bat-speed anchor); 0 = pure-ISO (pre-v2.9 behaviour).
HR_BARREL_BLEND_W: float = float(os.environ.get("DIAMOND_HR_BARREL_W", "0.6"))

# ---------------------------------------------------------------------------
# Personalized park HR factor (v2.5.0)
# ---------------------------------------------------------------------------
# personalized_park_hr_mult adjusts the empirical handedness HR factor for how a
# specific batter's spray + power make a park play shorter/longer for THEM. It is
# computed as a RATIO against the league-average hitter in the SAME park, so a
# crude carry curve and a coarse spray→fence interpolation largely cancel — what
# survives is this batter's deviation in pull tendency and exit velocity. The
# result multiplies on top of (never replaces) the empirical factor and is
# clamped, so it can only nudge, not dominate.
# Ratio exponent (personalization strength). Tuned on the 2025 full-season backtest
# (runs #62–66): HR Brier is flat across 0.4–0.6 (~0.1028, within noise) while
# high-bucket HR calibration improves as BETA drops, so 0.5 dominates the original
# 0.6 — equal Brier, ~14% less overconfidence. Env-overridable for future sweeps.
PARK_GEO_BETA: float = float(os.environ.get("DIAMOND_PARK_GEO_BETA", "0.5"))
PARK_GEO_LOGISTIC_SCALE_FT: float = 18.0         # ft spread of the clear-the-fence logistic
PARK_GEO_MULT_CLAMP: tuple[float, float] = (0.70, 1.50)
PARK_CARRY_BASE_FT: float = 375.0                # carry of a league-avg-EV authoritative fly
PARK_CARRY_PER_MPH: float = 4.5                  # ft of carry per mph EV above league
PARK_FENCE_PULL_FRAC: float = 0.55               # spray-angle interp: 0 = CF, 1 = foul line
PARK_FENCE_OPPO_FRAC: float = 0.55
PARK_WALL_STD_FT: float = 8.0                    # baseline wall height (no penalty at/below)
PARK_WALL_DIST_PER_FT: float = 1.5              # effective added distance per ft of wall over standard

# League-average batted-ball reference (2025, min 100 BIP) — the hitter the
# empirical park factor is implicitly built on; the personalization ratio is
# measured against this.
LEAGUE_PULL_PCT: float = 0.442
LEAGUE_CENTER_PCT: float = 0.284
LEAGUE_OPPO_PCT: float = 0.273
LEAGUE_FB_PCT: float = 0.265
LEAGUE_EV_MPH: float = 88.7

# ---------------------------------------------------------------------------
# Trajectory-level weather (v2.6.0)
# ---------------------------------------------------------------------------
# #4 retires the flat density×wind HR scalar: weather instead shifts a batter's
# fly-ball CARRY distance, and the HR effect is the change in P(clear the fence) —
# non-linear in the batter's power and the park (a tailwind turns a warning-track
# hitter's flyouts into homers but does nothing for a slap hitter). The two
# coefficients below are CALIBRATED, not textbook: tuned so the league-average
# batter's resulting multiplier tracks the old, run-environment-calibrated
# density×wind scalar over the real game-weather distribution. The physics supplies
# the per-batter SHAPE; the old scalar anchors the MAGNITUDE (there is no weather
# backtest to catch a drift in the run environment).
# Fitted (383 non-dome game-weathers × both hands) so the league-average batter's
# carry mult tracks the old density×wind scalar (RMSE 0.026); over 25.9k real
# batter×game evals the population mean drifts only −0.27% vs the old scalar, so the
# run environment is preserved. Effective, not textbook — anchored to the milder
# scalar through the steep logistic.
WIND_CARRY_FT_PER_MPH: float = 0.85   # ft of carry per mph out-blowing wind
DENSITY_CARRY_FRAC: float = 0.25      # share of carry that is drag-limited / ρ sensitivity
WEATHER_CARRY_HR_CLAMP: tuple[float, float] = (0.70, 1.50)
# Power gate: weather barely moves the HR rate of a hitter who can't drive the ball
# far enough to reach the wall, so the carry effect is scaled by exit velocity. =1.0 at
# league EV (so it leaves the run-env calibration untouched), →0 toward this floor.
WEATHER_CARRY_EV_FLOOR_MPH: float = 82.0

# ---------------------------------------------------------------------------
# Pitch-mix matchup regression (v2.1.0)
# ---------------------------------------------------------------------------
# Per-pitch-type batter/pitcher samples are thin, so the matchup model regresses
# each per-pitch-type rate toward its league baseline by sample size at query
# time (matchup.py), same empirical-Bayes shape as the skill blend. Phantom
# league-average pitches added to each sample:
# Bumped 100 → 200: thin early-season per-pitch-type samples have wildly noisy raw
# xwOBA, so regress them harder toward the league baseline. (Note: regression alone
# can't bound non-physical raw values — see the matchup clamps in matchup.py.)
REGRESSION_K_PITCHES_BATTER: int = 200
REGRESSION_K_PITCHES_PITCHER: int = 200

# A pitcher needs at least this many arsenal pitches (vs the batter's hand) before
# we trust a matchup; below it, fall back to the v2.0.0 season blend. Set low (30):
# even a spot starter's small sample carries signal once combine_component regresses
# it toward the league baseline, so 100 was discarding useful (regressed) signal.
MATCHUP_MIN_ARSENAL_PITCHES: int = 30

# When the batter has data for less than this share of the pitcher's mix, the
# uncovered share is filled with the batter's overall blend (partial fallback).
MATCHUP_MIN_COVERED_USAGE: float = 0.6

# ---------------------------------------------------------------------------
# Batter skill blending (L30 vs season)
# ---------------------------------------------------------------------------

# weight_l30 = min(pa_l30 / PA_L30_FULL_WEIGHT, PA_L30_BLEND_CAP)
# Cap on recent-form (last-30-day) weight in the skill blend. Set to 0.0 (recent
# form OFF) by the hot-hand audit: full-2025 backtest sweep at caps 0.0/0.3/0.6
# (runs #67/#68/#69, n=41,667) was MONOTONICALLY worse with more recency weight on
# H≥2/HR/K and tied on H≥1 — including in a May-15+ slice where L30 windows are
# fully populated. The Marcel prior + season sample carry the signal; streaks are
# noise. L30 columns remain computed/stored for display. Env-overridable
# (DIAMOND_PA_L30_CAP) for future sweeps.
PA_L30_FULL_WEIGHT: int = 150
PA_L30_BLEND_CAP: float = float(os.environ.get("DIAMOND_PA_L30_CAP", "0.0"))

# refresh-skills: minimum season PA to get a (regressed) batter_skill row.
# Below this, the sample is too noisy to blend even with regression — skip entirely.
MIN_PA_BATTER_SEASON: int = 30

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

# Fixed team PA budget (actual weights sum to ~37; informational only).
TEAM_PA_ESTIMATE: float = 38.0

# v2.0: expected PA by confirmed batting-order slot (1-9). The leadoff hitter gets
# ~0.8 more PA/game than the 9-hole; values from research (Tom Tango et al.) and
# used directly when a lineup is confirmed. Sum ≈ 38.3.
PA_BY_ORDER: dict[int, float] = {
    1: 4.62,
    2: 4.51,
    3: 4.40,
    4: 4.30,
    5: 4.20,
    6: 4.10,
    7: 4.00,
    8: 3.90,
    9: 3.80,
}

# Fallback when batting order is unknown (lineup not yet confirmed): flat PA for
# every projected starter, same as v1.
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

# Spray-personalized HIT park factor (v2.7, OFF by default). Exponent on the same
# clear-the-fence ratio the HR personalization uses — the physical story for hits
# (wall-ball doubles, deep-gap singles) is far weaker than for HR. MEASURED at 0.5
# on the full 2025 backtest (runs #97 control vs #98, both --park-personalized,
# leak-free prior-season profiles): hits got WORSE — H>=1 Brier 0.2368→0.2370,
# H>=2 0.1716→0.1720 with worse calibration (ECE 0.020→0.023). Stays 0.0 (multiplier
# exactly 1.0). Env-overridable (DIAMOND_PARK_HIT_GEO_BETA) to re-measure.
PARK_HIT_GEO_BETA: float = float(os.environ.get("DIAMOND_PARK_HIT_GEO_BETA", "0.0"))
PARK_HIT_GEO_MULT_CLAMP: tuple[float, float] = (0.92, 1.08)

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
# Air density HR adjustment (v2.3) — BallparkPal-style weather refinement
# ---------------------------------------------------------------------------
# When real humidity + barometric pressure are available, replace the temp-only HR
# term with a physical air-density model: a batted ball carries farther in thinner
# air (~4% distance per 10% density drop). Density falls with heat, humidity (water
# vapor is lighter than dry air), and low pressure / altitude.
#
# We score TODAY's density against the PARK's baseline density (same altitude, 70°F,
# 50% RH) so the day-to-day weather deviation is captured WITHOUT double-counting the
# park's altitude — that is already baked into park_factor_hr (3-yr Statcast factors).
#
# Specific gas constants (J/(kg·K)) for dry air and water vapor.
AIR_GAS_CONST_DRY: float = 287.058
AIR_GAS_CONST_VAPOR: float = 461.495
SEA_LEVEL_PRESSURE_HPA: float = 1013.25
WEATHER_BASELINE_HUMIDITY_PCT: float = 50.0  # park-baseline relative humidity
# HR factor = (baseline_density / today_density) ** exponent. Exponent ~2.6 calibrated
# so a 70°F→90°F sea-level day gives ~+10% HR, matching the prior temp-only model at
# that point; humidity/pressure then add on top. Clamp keeps a single day bounded.
DENSITY_HR_EXPONENT: float = 2.6
DENSITY_HR_CLAMP: tuple[float, float] = (0.82, 1.25)

# ---------------------------------------------------------------------------
# Per-PA rate and derived-count clamps
# ---------------------------------------------------------------------------

# Shrinkage toward league means, applied to the final adjusted per-PA rates
# before computing probabilities (v1.5.3). Curbs over-confidence at the tails
# from the compounding multiplicative adjustment chain. Higher = more shrinkage.
# Re-tuned 0.40 → 0.20 in v1.6.0: upstream empirical-Bayes regression now does
# most of the pulling, so this is a lighter final safety net (0.20 gave the
# flattest HR calibration; 0.40 over-shrank K, 0.0 let the tails drift).
SHRINKAGE_ALPHA: float = 0.20

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
# Team run expectation
# ---------------------------------------------------------------------------
# v2.2: lineup-driven linear weights on the deviation of each batter's
# fully-adjusted (matchup + park + weather, plus a bullpen blend) projected
# event rates from league average, anchored at LEAGUE_RUNS_PER_GAME_BASE.
# Replaces the v1 Pythagorean proxy (xwOBA^EXPONENT), which double-counted park
# and ignored the per-batter pitcher matchup. TEAM_RUNS_XWOBA_EXPONENT is retained
# only for backward reference and is no longer used by the model.

LEAGUE_RUNS_PER_GAME_BASE: float = 4.3
TEAM_RUNS_XWOBA_EXPONENT: float = 1.4  # deprecated (v1 proxy); unused by v2.2

# A team bats ~38 PA in a 9-inning game; the run anchor scales with actual PA.
LEAGUE_PA_PER_GAME: float = 38.0

# Non-HR hits split into singles/doubles/triples by league shares (Statcast era).
LEAGUE_1B_SHARE: float = 0.785
LEAGUE_2B_SHARE: float = 0.200
LEAGUE_3B_SHARE: float = 0.015

# Linear weights — run value of each event relative to a generic PA (wOBA-style).
LW_SINGLE: float = 0.47
LW_DOUBLE: float = 0.77
LW_TRIPLE: float = 1.04
LW_HOMERUN: float = 1.40
LW_WALK: float = 0.31

# Fraction of a lineup's plate appearances that face the opposing STARTER; the
# remainder face that team's bullpen (bullpen_skill). ~5.2 starter IP in 2024-25.
STARTER_PA_SHARE: float = 0.60

# ---------------------------------------------------------------------------
# First-inning run model (NRFI / YRFI)
# ---------------------------------------------------------------------------
# A team's first inning is led off by the top of the order, so it scores a bit more
# than an average inning: first-inning run expectancy ≈ full-game runs × this share
# (1.15/9 ≈ slightly above an even 1/9). The expected-runs → P(score) mapping is
# calibrated so a league-average matchup (4.3 R/team) gives ~0.50 YRFI.
FIRST_INNING_RUN_SHARE: float = 0.128
NRFI_PROB_COEFF: float = 0.63

# ---------------------------------------------------------------------------
# S2 — batter platoon split (experimental; OFF by default)
# ---------------------------------------------------------------------------
# Blend the batter's season/L30 skill toward their split vs the opposing pitcher's
# throwing hand (batter_platoon_skill) before it feeds the pitch-mix matchup. Kept
# OFF: the matchup layer, already computed vs the pitcher's hand, captures the
# platoon signal. RE-MEASURED on the full 2025 backtest (runs #95 vs #96): every
# market moved <=0.0002 Brier (H>=1 0.2368→0.2367, K>=1 0.2305→0.2303) — and this
# is the LEAK-OPTIMISTIC test (batter_platoon_skill is a season aggregate, so the
# backtest sees full-season splits), so the leak-free version can only be weaker.
# Dead signal. Env-overridable (DIAMOND_PLATOON_ENABLED=1) to re-measure if
# point-in-time platoon snapshots are ever built.
PLATOON_ENABLED: bool = os.environ.get("DIAMOND_PLATOON_ENABLED", "0") == "1"
MIN_PLATOON_PA: int = 25            # ignore splits thinner than this
PLATOON_FULL_WEIGHT_PA: int = 200   # PA at which the split reaches its max blend weight
PLATOON_WEIGHT_CAP: float = 0.50    # split never more than half the blended skill

# ---------------------------------------------------------------------------
# Probability output
# ---------------------------------------------------------------------------

PROB_DECIMAL_PLACES: int = 4
