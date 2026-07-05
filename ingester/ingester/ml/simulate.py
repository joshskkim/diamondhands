"""Lineup Monte-Carlo run simulator (v3 runs/totals).

Consumes per-batter per-PA outcome probabilities and simulates a 9-inning game many
times, advancing runners with a simple deterministic base-running model, to produce
expected team runs. The per-PA model gives a 5-class distribution {out, K, BB, non-HR
hit, HR}; non-HR hits are split into 1B/2B/3B by league ratios scaled by batter power.
"""
from __future__ import annotations

import numpy as np

# League split of non-HR hits into 1B/2B/3B (approx; 3B rare).
_NONHR_SPLIT = np.array([0.785, 0.200, 0.015])
# Outcome categories used by the simulator: 0 out, 1 K, 2 BB, 3 1B, 4 2B, 5 3B, 6 HR.


def split_to_7(probs5: np.ndarray) -> np.ndarray:
    """5-class {out,K,BB,hit,HR} -> 7-class {out,K,BB,1B,2B,3B,HR}; rows sum to 1."""
    out, k, bb, hit, hr = (probs5[:, i] for i in range(5))
    b1, b2, b3 = (hit * r for r in _NONHR_SPLIT)
    p = np.column_stack([out, k, bb, b1, b2, b3, hr])
    return p / p.sum(axis=1, keepdims=True)


def _sim_team(probs: np.ndarray, n_sims: int, rng: np.random.Generator) -> np.ndarray:
    """probs: (9,7). Return runs scored per sim (length n_sims)."""
    cum = np.cumsum(probs, axis=1)  # (9,7)
    runs = np.zeros(n_sims, dtype=np.int32)
    bptr = np.zeros(n_sims, dtype=np.int32)
    for _ in range(9):  # innings
        outs = np.zeros(n_sims, dtype=np.int32)
        b1 = np.zeros(n_sims, bool)
        b2 = np.zeros(n_sims, bool)
        b3 = np.zeros(n_sims, bool)
        while (outs < 3).any():
            s = np.where(outs < 3)[0]
            u = rng.random(len(s))
            oc = (u[:, None] < cum[bptr[s]]).argmax(axis=1)
            bptr[s] = (bptr[s] + 1) % 9

            def sub(cat):
                return s[oc == cat]

            outs[s[oc <= 1]] += 1  # out or K
            for cat, scorers in ((2, "bb"), (3, "1b"), (4, "2b"), (5, "3b"), (6, "hr")):
                ss = sub(cat)
                if len(ss) == 0:
                    continue
                r1, r2, r3 = b1[ss].copy(), b2[ss].copy(), b3[ss].copy()
                if cat == 2:   # BB (force; run only if loaded)
                    runs[ss] += (r1 & r2 & r3)
                    b3[ss] = r3 | (r1 & r2)
                    b2[ss] = r2 | r1
                    b1[ss] = True
                elif cat == 3:  # 1B: 3rd scores, others advance one
                    runs[ss] += r3
                    b3[ss] = r2
                    b2[ss] = r1
                    b1[ss] = True
                elif cat == 4:  # 2B: 2nd & 3rd score, 1st->3rd
                    runs[ss] += r2 + r3
                    b3[ss] = r1
                    b2[ss] = True
                    b1[ss] = False
                elif cat == 5:  # 3B: all runners score
                    runs[ss] += r1 + r2 + r3
                    b3[ss] = True
                    b2[ss] = False
                    b1[ss] = False
                else:           # HR
                    runs[ss] += 1 + r1 + r2 + r3
                    b1[ss] = False
                    b2[ss] = False
                    b3[ss] = False
    return runs


def expected_total_runs(home7: np.ndarray, away7: np.ndarray, n_sims: int = 400, seed: int = 0) -> float:
    """Mean total runs (both teams) over n_sims simulated games."""
    rng = np.random.default_rng(seed)
    return float(_sim_team(home7, n_sims, rng).mean() + _sim_team(away7, n_sims, rng).mean())
