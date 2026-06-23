"""Unified Monte-Carlo game simulator (BallparkPal-style).

Drives the existing base-running engine off our *projected* per-batter rates (no ML
model needed), simulates a game many times, and derives EVERYTHING from the one run:
team-run distributions (→ expected runs, win prob, over/under any total line),
period (first-N-innings) run distributions (→ NRFI/YRFI for F1 and F5/F3/F7
moneyline/run-line/totals), and per-batter event counts (→ hit/HR/TB/K props).

Period markets note: because our per-batter rates are adjusted for the opposing
*starter* (no bullpen, no times-through-order penalty), the first-N-innings outputs
(F1/F3/F5) — which sportsbooks offer precisely because the early innings are
starter-dominated — are the engine's most rigorous predictions. The full-game (F9)
output extrapolates the starter across all nine innings and is a serviceable but
weaker estimate.

Outcome categories (7): 0 out, 1 K, 2 BB, 3 1B, 4 2B, 5 3B, 6 HR.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Inning counts at which we snapshot cumulative runs (first-N-innings markets).
# 1 = NRFI/YRFI (F1), 5 = first five (F5), 9 = full game.
PERIODS: tuple[int, ...] = (1, 3, 5, 7, 9)

from ingester.projection import constants as C
from ingester.projection.batter_model import BatterProjection
from ingester.projection.constants import (
    LEAGUE_1B_SHARE,
    LEAGUE_2B_SHARE,
    LEAGUE_3B_SHARE,
    LEAGUE_BB_PER_PA,
)

_TB_BY_CAT = {3: 1, 4: 2, 5: 3, 6: 4}

# Effective base-running advancement rates. These are *calibrated*, not literal
# observed rates: a hits+walks model with conservative advancement scores ~30% below
# MLB average, so these absorb unmodeled second-order advancement (extra-base
# baserunning, errors). Jointly tuned so a league-average lineup scores ~4.4 R/9 and
# YRFI ~0.49, matching the empirical 2026 run environment (4.48 R/team, 8.97 total).
P_2ND_SCORES_ON_1B = 0.72   # runner on 2nd scores on a single
P_1ST_TO_3RD_ON_1B = 0.44   # runner on 1st takes third on a single
P_1ST_SCORES_ON_2B = 0.62   # runner on 1st scores on a double
P_RUN_SCORES_ON_OUT = 0.60  # runner on 3rd scores on an in-play out w/ <2 outs (sac fly / groundout)
# Catch-all for stolen bases / wild pitches / passed balls / reached-on-error. Each PA
# an eligible lead runner advances one base into an open base with this prob.
P_EXTRA_ADVANCE = 0.12


def batter_pa_probs(proj: BatterProjection) -> np.ndarray:
    """7-class per-PA outcome distribution from a batter's fully-adjusted rates."""
    k = proj.adjusted.k_per_pa
    hr = proj.adjusted.hr_per_pa
    hit = proj.adjusted.hit_per_pa
    non_hr = max(hit - hr, 0.0)
    bb = LEAGUE_BB_PER_PA
    b1 = non_hr * LEAGUE_1B_SHARE
    b2 = non_hr * LEAGUE_2B_SHARE
    b3 = non_hr * LEAGUE_3B_SHARE
    out = max(1.0 - (k + bb + b1 + b2 + b3 + hr), 0.0)
    p = np.array([out, k, bb, b1, b2, b3, hr], dtype=float)
    return p / p.sum()


def lineup_probs(projs: list[BatterProjection]) -> np.ndarray:
    """(9,7) per-PA outcome matrix for a 9-batter lineup (in batting order)."""
    return np.vstack([batter_pa_probs(p) for p in projs[:9]])


def tto_multipliers(turn: int, fb_share: float) -> tuple[float, float]:
    """(offense_mult, k_mult) for a time-through-the-order (0-based) vs a starter.

    turn 0 = 1st time through (no penalty). The offensive bump scales with the starter's
    fastball-usage share relative to league average (fastball-heavy arms decay more); the
    K rate is relieved by a fraction of that bump. See constants.py TTO_* for the (OFF by
    default, unvalidated) coefficients.
    """
    if turn <= 0:
        return 1.0, 1.0
    base = C.TTO_OFFENSE_DELTA_2ND if turn == 1 else C.TTO_OFFENSE_DELTA_3RD
    fb_factor = min(max(fb_share / C.TTO_FB_REFERENCE, C.TTO_FB_FACTOR_MIN), C.TTO_FB_FACTOR_MAX)
    off_delta = base * fb_factor
    return 1.0 + off_delta, 1.0 - off_delta * C.TTO_K_RELIEF_FRACTION


def _apply_tto_probs(probs: np.ndarray, off_mult: float, k_mult: float) -> np.ndarray:
    """Scale a (9,7) per-PA matrix for a TTO penalty and renormalize.

    Cats: 0 out, 1 K, 2 BB, 3 1B, 4 2B, 5 3B, 6 HR. Hits+HR (3..6) scale by off_mult,
    K (1) by k_mult, BB held; the 'out' category absorbs the difference so each row
    still sums to 1 (clamped non-negative).
    """
    p = probs.copy()
    p[:, 3:7] *= off_mult
    p[:, 1] *= k_mult
    p[:, 0] = np.maximum(1.0 - p[:, 1:].sum(axis=1), 0.0)
    return p / p.sum(axis=1, keepdims=True)


def _tto_cum_stack(probs: np.ndarray, fb_share: float) -> np.ndarray:
    """(3,9,7) cumulative per-PA matrices for times-through 1st/2nd/3rd+ vs a starter."""
    mats = [np.cumsum(_apply_tto_probs(probs, *tto_multipliers(turn, fb_share)), axis=1)
            for turn in range(3)]
    return np.stack(mats)


@dataclass
class TeamSim:
    runs: np.ndarray            # (n_sims,) total runs (== period_runs at full game)
    period_runs: dict[int, np.ndarray]  # innings_completed -> (n_sims,) cumulative runs
    slot_hits: np.ndarray       # (n_sims, 9)
    slot_hr: np.ndarray         # (n_sims, 9)
    slot_tb: np.ndarray         # (n_sims, 9)
    slot_k: np.ndarray          # (n_sims, 9)
    starter_hits: np.ndarray    # (n_sims,) team hits through the opposing starter's exit
    starter_runs: np.ndarray    # (n_sims,) team runs through the opposing starter's exit


def _sim_team(
    probs: np.ndarray,
    n_sims: int,
    rng: np.random.Generator,
    innings: int = 9,
    periods: tuple[int, ...] = PERIODS,
    bullpen_probs: np.ndarray | None = None,
    starter_innings: int = 5,
    starter_fb_share: float | None = None,
) -> TeamSim:
    """Simulate one team's offense `n_sims` times; track runs, per-period runs, per-slot events.

    If `bullpen_probs` is given, the starter's rates (`probs`) are faced for the first
    `starter_innings` innings and the bullpen's rates thereafter. This keeps the
    first-N-innings (F1/F3/F5) markets purely starter-driven while making the full-game
    output bullpen-aware. Default (None) faces the starter all game.

    `starter_fb_share` (with constants.TTO_ENABLED) turns on the times-through-the-order
    penalty: the starter's rates are raised on the 2nd/3rd+ time through the lineup,
    scaled by his fastball share. None or TTO disabled → starter rates are flat (current
    behavior, bit-for-bit).
    """
    cum_starter = np.cumsum(probs, axis=1)
    cum_bullpen = np.cumsum(bullpen_probs, axis=1) if bullpen_probs is not None else None
    # Per-time-through starter matrices (3,9,7), only when TTO is enabled + a fb share given.
    tto_cum = (_tto_cum_stack(probs, starter_fb_share)
               if C.TTO_ENABLED and starter_fb_share is not None else None)
    pa_count = np.zeros(n_sims, dtype=np.int32)  # PAs taken so far (per sim) → time-through index
    runs = np.zeros(n_sims, dtype=np.int32)
    team_hits = np.zeros(n_sims, dtype=np.int32)  # cumulative team hits (for pitcher props)
    period_runs: dict[int, np.ndarray] = {}
    period_set = {p for p in periods if p <= innings}
    # Inning the starter is pulled at: the whole-inning boundary nearest his projected
    # depth. The sim advances by full innings, so a 5.4-IP projection exits after the 5th.
    # The opposing-team runs/hits accumulated through here are the starter's earned-runs
    # and hits-allowed distributions (pitcher props).
    starter_exit = int(min(max(round(starter_innings), 1), innings))
    starter_hits = np.zeros(n_sims, dtype=np.int32)
    starter_runs = np.zeros(n_sims, dtype=np.int32)
    slot_hits = np.zeros((n_sims, 9), dtype=np.int32)
    slot_hr = np.zeros((n_sims, 9), dtype=np.int32)
    slot_tb = np.zeros((n_sims, 9), dtype=np.int32)
    slot_k = np.zeros((n_sims, 9), dtype=np.int32)
    bptr = np.zeros(n_sims, dtype=np.int32)

    for inning in range(innings):
        facing_bullpen = cum_bullpen is not None and inning >= starter_innings
        cum = cum_bullpen if facing_bullpen else cum_starter
        outs = np.zeros(n_sims, dtype=np.int32)
        b1 = np.zeros(n_sims, bool); b2 = np.zeros(n_sims, bool); b3 = np.zeros(n_sims, bool)
        while (outs < 3).any():
            s = np.where(outs < 3)[0]
            slot = bptr[s].copy()
            u = rng.random(len(s))
            if tto_cum is not None and not facing_bullpen:
                # Per-sim time-through index (0/1/2+) picks the right starter matrix.
                tidx = np.minimum(pa_count[s] // 9, 2)
                cum_s = tto_cum[tidx, bptr[s]]
            else:
                cum_s = cum[bptr[s]]
            oc = (u[:, None] < cum_s).argmax(axis=1)
            pa_count[s] += 1
            bptr[s] = (bptr[s] + 1) % 9

            # per-slot props
            km = oc == 1
            if km.any():
                np.add.at(slot_k, (s[km], slot[km]), 1)
            for cat, tb in _TB_BY_CAT.items():
                cm = oc == cat
                if cm.any():
                    np.add.at(slot_hits, (s[cm], slot[cm]), 1)
                    np.add.at(slot_tb, (s[cm], slot[cm]), tb)
                    team_hits[s[cm]] += 1
            hm = oc == 6
            if hm.any():
                np.add.at(slot_hr, (s[hm], slot[hm]), 1)

            # Sac fly / productive out: runner on 3rd scores on an in-play out (not a K)
            # when there are fewer than 2 outs.
            ipo = s[(oc == 0) & (outs[s] < 2) & b3[s]]
            if len(ipo):
                scored = rng.random(len(ipo)) < P_RUN_SCORES_ON_OUT
                runs[ipo] += scored
                b3[ipo] = b3[ipo] & ~scored

            outs[s[oc <= 1]] += 1  # in-play out or K

            def sub(cat):
                return s[oc == cat]

            for cat in (2, 3, 4, 5, 6):
                ss = sub(cat)
                if len(ss) == 0:
                    continue
                r1, r2, r3 = b1[ss].copy(), b2[ss].copy(), b3[ss].copy()
                if cat == 2:    # BB: force; run only if bases loaded
                    runs[ss] += (r1 & r2 & r3)
                    b3[ss] = r3 | (r1 & r2); b2[ss] = r2 | r1; b1[ss] = True
                elif cat == 3:  # 1B: r3 scores; r2 scores ~60%, else 3rd; r1 -> 2nd/3rd
                    score2 = r2 & (rng.random(len(ss)) < P_2ND_SCORES_ON_1B)
                    stay3_from2 = r2 & ~score2
                    to3_from1 = r1 & (rng.random(len(ss)) < P_1ST_TO_3RD_ON_1B) & ~stay3_from2
                    runs[ss] += r3 + score2
                    b3[ss] = stay3_from2 | to3_from1
                    b2[ss] = r1 & ~to3_from1
                    b1[ss] = True
                elif cat == 4:  # 2B: r2,r3 score; r1 scores ~45%, else 3rd
                    score1 = r1 & (rng.random(len(ss)) < P_1ST_SCORES_ON_2B)
                    runs[ss] += r2 + r3 + score1
                    b3[ss] = r1 & ~score1
                    b2[ss] = True
                    b1[ss] = False
                elif cat == 5:  # 3B
                    runs[ss] += r1 + r2 + r3
                    b3[ss] = True; b2[ss] = False; b1[ss] = False
                else:           # HR
                    runs[ss] += 1 + r1 + r2 + r3
                    b1[ss] = False; b2[ss] = False; b3[ss] = False

            # Extra advancement (SB/WP/PB/ROE) into open bases, lead runner first.
            # Only for innings still in progress (a WP after the 3rd out scores nobody).
            a = s[outs[s] < 3]
            if len(a):
                m3 = b3[a] & (rng.random(len(a)) < P_EXTRA_ADVANCE)
                runs[a] += m3
                b3[a] = b3[a] & ~m3
                m2 = b2[a] & ~b3[a] & (rng.random(len(a)) < P_EXTRA_ADVANCE)
                b3[a] = b3[a] | m2
                b2[a] = b2[a] & ~m2
                m1 = b1[a] & ~b2[a] & (rng.random(len(a)) < P_EXTRA_ADVANCE)
                b2[a] = b2[a] | m1
                b1[a] = b1[a] & ~m1
        done = inning + 1
        if done in period_set:
            period_runs[done] = runs.copy()
        if done == starter_exit:
            starter_hits = team_hits.copy()
            starter_runs = runs.copy()

    return TeamSim(runs, period_runs, slot_hits, slot_hr, slot_tb, slot_k,
                   starter_hits, starter_runs)


@dataclass
class BatterProps:
    p_hit_1plus: float
    p_hit_2plus: float
    p_hr: float
    p_k_1plus: float
    expected_tb: float
    expected_hits: float


# Histogram bin ceilings for the starting-pitcher prop distributions. Books rarely set
# hits-allowed lines above ~7.5 or earned-runs above ~3.5, so these comfortably cover
# every quotable O/U while keeping the stored arrays small.
PITCHER_HITS_HIST_MAX = 12
PITCHER_ER_HIST_MAX = 8


@dataclass
class PitcherProps:
    """Starting-pitcher prop distributions over the starter's projected outing, derived
    from the opposing team's hits/runs accumulated through the starter's exit inning.
    Earned runs are approximated by total runs (the sim has no error model — a small,
    slightly conservative bias)."""
    expected_hits: float
    expected_er: float
    hits_hist: list[int]   # counts over n_sims, bins 0..PITCHER_HITS_HIST_MAX (last is >=)
    er_hist: list[int]     # counts over n_sims, bins 0..PITCHER_ER_HIST_MAX (last is >=)


def _counts_hist(arr: np.ndarray, max_bin: int) -> list[int]:
    """Histogram of integer counts, bins 0..max_bin (last bin is >=max_bin)."""
    clipped = np.minimum(arr, max_bin)
    return np.bincount(clipped, minlength=max_bin + 1).astype(int).tolist()


def _pitcher_props(team: TeamSim) -> PitcherProps:
    """The opposing starter's prop distributions from the team that faced him."""
    return PitcherProps(
        expected_hits=float(team.starter_hits.mean()),
        expected_er=float(team.starter_runs.mean()),
        hits_hist=_counts_hist(team.starter_hits, PITCHER_HITS_HIST_MAX),
        er_hist=_counts_hist(team.starter_runs, PITCHER_ER_HIST_MAX),
    )


@dataclass
class PeriodMarket:
    """First-N-innings market summary derived from the simulated run distributions."""
    innings: int
    home_runs: np.ndarray       # (n_sims,) cumulative home runs after `innings`
    away_runs: np.ndarray

    @property
    def expected_home(self) -> float:
        return float(self.home_runs.mean())

    @property
    def expected_away(self) -> float:
        return float(self.away_runs.mean())

    @property
    def expected_total(self) -> float:
        return float((self.home_runs + self.away_runs).mean())

    @property
    def p_home_lead(self) -> float:
        """Moneyline: P(home leads). Ties (period push) are reported separately."""
        return float((self.home_runs > self.away_runs).mean())

    @property
    def p_away_lead(self) -> float:
        return float((self.away_runs > self.home_runs).mean())

    @property
    def p_tie(self) -> float:
        return float((self.home_runs == self.away_runs).mean())

    def prob_over(self, line: float) -> float:
        """P(combined runs strictly over `line`) for this period."""
        return float(((self.home_runs + self.away_runs) > line).mean())

    def p_home_cover(self, line: float) -> float:
        """P(home covers a run line of `line` (signed, e.g. -1.5)). Integer margins
        never land on a .5 line, so home + away cover sum to 1 (no push)."""
        return float(((self.home_runs - self.away_runs) > -line).mean())

    def p_away_cover(self, line: float) -> float:
        """P(away covers a run line of `line` (signed, e.g. +1.5))."""
        return float(((self.away_runs - self.home_runs) > -line).mean())

    def total_hist(self, max_runs: int) -> list[int]:
        """Histogram of combined-run counts, bins 0..max_runs (last bin is >=max_runs)."""
        total = self.home_runs + self.away_runs
        clipped = np.minimum(total, max_runs)
        return np.bincount(clipped, minlength=max_runs + 1).astype(int).tolist()


@dataclass
class GameSim:
    n_sims: int
    periods: dict[int, PeriodMarket]   # innings_completed -> market (1,3,5,7,9)
    home_props: list[BatterProps]      # per lineup slot 0..8
    away_props: list[BatterProps]
    home_pitcher_props: PitcherProps   # the HOME starter's hits-allowed / earned-runs
    away_pitcher_props: PitcherProps   # the AWAY starter's hits-allowed / earned-runs
    # Raw per-sim team arrays, retained so the JOINT distribution between legs can be
    # recomputed on demand (correlation / same-game-parlay pricing). Not persisted — the
    # runner stores only the marginals above. None on a GameSim built without them.
    # NOTE: the two teams are drawn from INDEPENDENT rng streams, so cross-team player
    # correlation is ~0 by construction; within-team and player-vs-game-total joints are
    # real (a hitter's big day rides the same simulated game as his team's runs).
    home: "TeamSim | None" = None
    away: "TeamSim | None" = None

    @property
    def full(self) -> PeriodMarket:
        """Full-game (9-inning) market."""
        return self.periods[max(self.periods)]

    @property
    def p_home_cover_1_5(self) -> float:
        """Full-game run line: P(home covers -1.5)."""
        return self.full.p_home_cover(-1.5)

    @property
    def p_away_cover_1_5(self) -> float:
        """Full-game run line: P(away covers +1.5)."""
        return self.full.p_away_cover(1.5)

    @property
    def f5(self) -> PeriodMarket:
        return self.periods[5]

    # --- Full-game convenience accessors (back-compatible API) ---
    @property
    def expected_home_runs(self) -> float:
        return self.full.expected_home

    @property
    def expected_away_runs(self) -> float:
        return self.full.expected_away

    @property
    def expected_total(self) -> float:
        return self.full.expected_total

    @property
    def p_home_win(self) -> float:
        """Full-game win prob; extra-inning ties split as a coin flip."""
        f = self.full
        return f.p_home_lead + 0.5 * f.p_tie

    @property
    def home_runs(self) -> np.ndarray:
        return self.full.home_runs

    @property
    def away_runs(self) -> np.ndarray:
        return self.full.away_runs

    @property
    def p_yrfi(self) -> float:
        """P(a run scores in the 1st inning) — F1 / YRFI."""
        return self.periods[1].prob_over(0)


def _slot_props(team: TeamSim) -> list[BatterProps]:
    props: list[BatterProps] = []
    n = team.runs.shape[0]
    for slot in range(9):
        hits = team.slot_hits[:, slot]
        props.append(BatterProps(
            p_hit_1plus=float((hits >= 1).mean()),
            p_hit_2plus=float((hits >= 2).mean()),
            p_hr=float((team.slot_hr[:, slot] >= 1).mean()),
            p_k_1plus=float((team.slot_k[:, slot] >= 1).mean()),
            expected_tb=float(team.slot_tb[:, slot].mean()),
            expected_hits=float(hits.mean()),
        ))
    return props


def simulate_game(
    home_lineup: list[BatterProjection],
    away_lineup: list[BatterProjection],
    n_sims: int = 1000,
    seed: int = 0,
    home_bullpen: list[BatterProjection] | None = None,
    away_bullpen: list[BatterProjection] | None = None,
    starter_innings: int = 5,
    home_starter_innings: int | None = None,
    away_starter_innings: int | None = None,
    home_starter_fb_share: float | None = None,
    away_starter_fb_share: float | None = None,
) -> GameSim:
    """Simulate a full game n_sims times; derive per-period markets and props.

    `home_bullpen`/`away_bullpen` are the same lineups re-projected against the opposing
    bullpen; when given, the bullpen is faced after `starter_innings` innings so the
    full-game output is bullpen-aware while F1/F3/F5 stay starter-driven.

    `home_starter_innings`/`away_starter_innings` (v2.8): the depth of the OPPOSING
    starter each lineup faces, from the workload model — the home lineup faces the away
    starter, so `home_starter_innings` is the away starter's projected innings. Both
    default to the flat `starter_innings` when not supplied.

    `home_starter_fb_share`/`away_starter_fb_share` (Phase 2a): the fastball-usage share
    of the OPPOSING starter each lineup faces, for the times-through-order penalty (only
    active when constants.TTO_ENABLED). Same orientation as the innings args.
    """
    # Independent RNG streams per team so one team's late innings (bullpen) can't shift
    # the other team's draws — this keeps F1/F5 invariant to the bullpen inputs.
    rng_home, rng_away = (np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(2))
    home_pen = lineup_probs(home_bullpen) if home_bullpen is not None else None
    away_pen = lineup_probs(away_bullpen) if away_bullpen is not None else None
    home = _sim_team(lineup_probs(home_lineup), n_sims, rng_home,
                     bullpen_probs=home_pen,
                     starter_innings=home_starter_innings or starter_innings,
                     starter_fb_share=home_starter_fb_share)
    away = _sim_team(lineup_probs(away_lineup), n_sims, rng_away,
                     bullpen_probs=away_pen,
                     starter_innings=away_starter_innings or starter_innings,
                     starter_fb_share=away_starter_fb_share)

    periods = {
        p: PeriodMarket(innings=p, home_runs=home.period_runs[p], away_runs=away.period_runs[p])
        for p in home.period_runs
    }

    return GameSim(
        n_sims=n_sims,
        periods=periods,
        home_props=_slot_props(home),
        away_props=_slot_props(away),
        # A starter's hits/runs allowed = what the OPPOSING lineup put up against him.
        home_pitcher_props=_pitcher_props(away),
        away_pitcher_props=_pitcher_props(home),
        home=home,
        away=away,
    )


def prob_over(total_runs: np.ndarray, line: float) -> float:
    """P(total runs strictly over `line`) from the simulated distribution."""
    return float((total_runs > line).mean())
