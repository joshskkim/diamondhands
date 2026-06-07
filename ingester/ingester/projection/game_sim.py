"""Unified Monte-Carlo game simulator (BallparkPal-style).

Drives the existing base-running engine off our *projected* per-batter rates (no ML
model needed), simulates a game many times, and derives EVERYTHING from the one run:
team-run distributions (→ expected runs, win prob, over/under any total line),
first-inning runs (→ NRFI/YRFI), and per-batter event counts (→ hit/HR/TB/K props).

Outcome categories (7): 0 out, 1 K, 2 BB, 3 1B, 4 2B, 5 3B, 6 HR.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

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


@dataclass
class TeamSim:
    runs: np.ndarray            # (n_sims,) total runs
    first_inning_runs: np.ndarray  # (n_sims,) runs in the 1st inning
    slot_hits: np.ndarray       # (n_sims, 9)
    slot_hr: np.ndarray         # (n_sims, 9)
    slot_tb: np.ndarray         # (n_sims, 9)
    slot_k: np.ndarray          # (n_sims, 9)


def _sim_team(probs: np.ndarray, n_sims: int, rng: np.random.Generator, innings: int = 9) -> TeamSim:
    """Simulate one team's offense `n_sims` times; track runs, 1st-inning runs, per-slot events."""
    cum = np.cumsum(probs, axis=1)
    runs = np.zeros(n_sims, dtype=np.int32)
    first_inning = np.zeros(n_sims, dtype=np.int32)
    slot_hits = np.zeros((n_sims, 9), dtype=np.int32)
    slot_hr = np.zeros((n_sims, 9), dtype=np.int32)
    slot_tb = np.zeros((n_sims, 9), dtype=np.int32)
    slot_k = np.zeros((n_sims, 9), dtype=np.int32)
    bptr = np.zeros(n_sims, dtype=np.int32)

    for inning in range(innings):
        outs = np.zeros(n_sims, dtype=np.int32)
        b1 = np.zeros(n_sims, bool); b2 = np.zeros(n_sims, bool); b3 = np.zeros(n_sims, bool)
        while (outs < 3).any():
            s = np.where(outs < 3)[0]
            slot = bptr[s].copy()
            u = rng.random(len(s))
            oc = (u[:, None] < cum[bptr[s]]).argmax(axis=1)
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
        if inning == 0:
            first_inning = runs.copy()

    return TeamSim(runs, first_inning, slot_hits, slot_hr, slot_tb, slot_k)


@dataclass
class BatterProps:
    p_hit_1plus: float
    p_hit_2plus: float
    p_hr: float
    p_k_1plus: float
    expected_tb: float
    expected_hits: float


@dataclass
class GameSim:
    n_sims: int
    expected_home_runs: float
    expected_away_runs: float
    expected_total: float
    p_home_win: float
    p_yrfi: float
    home_runs: np.ndarray       # (n_sims,) for over/under on any line
    away_runs: np.ndarray
    home_props: list[BatterProps]   # per lineup slot 0..8
    away_props: list[BatterProps]


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
) -> GameSim:
    """Simulate a full game n_sims times; derive totals, win prob, NRFI, and props."""
    rng = np.random.default_rng(seed)
    home = _sim_team(lineup_probs(home_lineup), n_sims, rng)
    away = _sim_team(lineup_probs(away_lineup), n_sims, rng)

    # Win prob: count home wins; split ties evenly (extra innings are a coin flip).
    home_win = home.runs > away.runs
    tie = home.runs == away.runs
    p_home_win = float(home_win.mean() + 0.5 * tie.mean())

    yrfi = (home.first_inning_runs > 0) | (away.first_inning_runs > 0)

    return GameSim(
        n_sims=n_sims,
        expected_home_runs=float(home.runs.mean()),
        expected_away_runs=float(away.runs.mean()),
        expected_total=float((home.runs + away.runs).mean()),
        p_home_win=p_home_win,
        p_yrfi=float(yrfi.mean()),
        home_runs=home.runs,
        away_runs=away.runs,
        home_props=_slot_props(home),
        away_props=_slot_props(away),
    )


def prob_over(total_runs: np.ndarray, line: float) -> float:
    """P(total runs strictly over `line`) from the simulated distribution."""
    return float((total_runs > line).mean())
