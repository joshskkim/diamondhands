# Prop-market evaluation: singles / doubles / triples / stolen bases, and sim count

_2026-07-09._ Two questions: (1) are batter hit-type props (1B / 2B / 3B) and stolen-base
props worth projecting and serving? (2) does raising the Monte-Carlo simulation count improve
the props we already serve?

**TL;DR.** Defer all four new batter markets — none can be validated or bet profitably today.
Singles/doubles/triples carry no batter-specific signal under the current sim (fixed league
split) and, more fundamentally, **cannot be backtested** because we never graded 1B/2B/3B.
Stolen bases have **zero input data** and no grading column — a genuine new pipeline, not a
tweak. Separately, the sim count was raised 4000 → 16000 (a proven, near-free precision win).

---

## 1. Batter hit-type props (singles / doubles / triples)

### What the sim does today
The game simulator already draws a **7-class per-PA outcome** — `[out, K, BB, 1B, 2B, 3B, HR]`
(`ingester/ingester/projection/game_sim.py:54-66`). So 1B/2B/3B exist as distinct events. But
the split of a batter's non-HR hits into single/double/triple is a **fixed league-wide
constant**, identical for every hitter (`constants.py:487-490`):

```python
LEAGUE_1B_SHARE = 0.785
LEAGUE_2B_SHARE = 0.200
LEAGUE_3B_SHARE = 0.015
```

Consequence: a per-batter "doubles" or "singles" projection would just be that batter's total
non-HR hit projection **rescaled by a constant**. A slap hitter and a power hitter with the same
projected hit rate get the *same* implied double rate. There is no edge to find — the market
would rank identically to the retired "1+ hit" card (singles are ~79% of non-HR hits, so a
"1+ singles" prop ≈ the old "1+ hit" prop we already dropped).

### The harder blocker: we can't grade them
`player_game_stats` (`db/migrations/V1__schema.sql:139`) stores `hits`, `home_runs`,
`total_bases`, `strikeouts`, `walks`, `runs`, `rbi` — but **not singles, doubles, or triples**.
A repo-wide search of the migrations for `singles|doubles|triples` returns nothing. So even a
correct hit-type model has **no ground truth to backtest against**; we could ship a number but
never prove it beats the market or the naive rescale. That violates the eval-first bar we hold
every other lever to.

### What a real build would require (deferred)
1. **Per-batter hit-type shares** replacing the three `LEAGUE_*_SHARE` constants — driven by
   `batter_skill.iso` and `batter_batted_ball` (LD% / FB% / launch speed / pull%), which we
   already ingest. This is the tractable part.
2. **Grading**: extend the boxscore backfill to persist 1B/2B/3B in `player_game_stats` (new
   columns), then accrue enough history to backtest.
3. **Odds coverage** (see §3).

**Verdict.** Defer. If revisited, **doubles** is the only mildly interesting candidate (real
ISO/batted-ball signal, occasionally quoted). **Skip triples** — too rare (~1.5% of hits) and
essentially never quoted. Singles add nothing over the retired hit card.

---

## 2. Stolen-base props

There is **no stolen-base model and no input data**. A repo-wide search for
`sprint_speed | stolen_base | sb_rate | sb_attempt | caught_steal` across `ingester/`,
`db/migrations/`, and `api/src/` returns **zero matches**. In the sim, SB is not an event at
all — it's folded into a single flat catch-all constant alongside wild pitches, passed balls,
and reached-on-error (`game_sim.py:49-51`):

```python
# Catch-all for stolen bases / wild pitches / passed balls / reached-on-error.
P_EXTRA_ADVANCE = 0.12
```

There is no per-runner sprint speed, no SB attempt/success rate, and `player_game_stats` has no
`stolen_bases` column — so SB isn't even graded historically.

### What a real build would require (deferred)
- A **new data ingest**: Statcast sprint speed + SB/CS/attempt rates (available via
  pybaseball / Baseball Savant, already a dependency).
- New schema (columns/table) for the rates and for **grading** SB outcomes.
- A **per-runner SB event** in `_sim_team()` replacing/supplementing the flat `P_EXTRA_ADVANCE`.

**Verdict.** Defer — the largest lift of the four, the highest-variance market, and (per §3) the
thinnest liquidity. Only worth it as a deliberate, standalone project.

---

## 3. Odds liquidity / coverage caveat (applies to all four)

`odds_api.py` `PROP_MARKETS` (the complete set of prop keys we request) has **no**
`batter_singles`, `batter_doubles`, `batter_triples`, or `batter_stolen_bases` entries. Adding
them is possible (they are valid Odds-API MLB keys), but:

- Every added prop key **increases the per-event credit cost** of `refresh-odds`.
- Our books are `fanduel,draftkings,fanatics`, and the code already notes Fanatics/FanDuel
  "may serve game markets only, not batter props" — coverage for niche batter props is thin.

So even a correct model may have **little or no price to bet against** — a second reason the ROI
on these markets is low right now.

---

## 4. Does raising the Monte-Carlo sim count help? (Yes — shipped 4000 → 16000)

`SIM_N_SIMS` was hardcoded at 4000 (`runner.py:72`), consumed once per game
(`runner.py:1302-1312`) with a **fixed seed = `game_id`**. Raising `n` reduces Monte-Carlo
*sampling error* (`≈ sqrt(p(1-p)/n)`), not model bias — and because the seed is fixed, that
error is a **fixed per-game deviation** of the served number from the model's true probability,
not day-to-day flicker.

### Experiment
For each `n ∈ {4000, 8000, 16000, 50000}` we ran 24 independent seeds and measured the
**across-seed standard deviation** of each served prop (the honest MC standard error at that
`n`), plus bias vs a 200k-sim anchor. Inputs were synthetic-but-realistic lineups spanning
weak/average/contact/slugger archetypes so rare tails (TB≥4, HRR≥4) are exercised. (Script:
scratchpad `sim_convergence.py`; not committed.)

**MC standard error (SD across 24 seeds), percentage points:**

| market            | n=4,000 | n=8,000 | n=16,000 | n=50,000 | truth% |
|-------------------|--------:|--------:|---------:|---------:|-------:|
| slugger HRR o1.5  |    0.84 |    0.51 |     0.34 |     0.20 |   62.0 |
| slugger TB o1.5   |    0.72 |    0.47 |     0.42 |     0.23 |   51.2 |
| slugger P(HR)     |    0.65 |    0.42 |     0.33 |     0.19 |   25.6 |
| slugger P(K 1+)   |    0.61 |    0.35 |     0.30 |     0.19 |   76.1 |
| average HRR o1.5  |    0.87 |    0.44 |     0.38 |     0.23 |   53.2 |
| average TB o1.5   |    0.89 |    0.52 |     0.31 |     0.23 |   41.5 |
| average P(HR)     |    0.46 |    0.48 |     0.24 |     0.12 |   13.3 |
| slugger TB ≥4 (tail) | 0.65 |    0.47 |     0.36 |     0.20 |   29.4 |
| slugger HRR ≥4 (tail)| 0.66 |    0.53 |     0.25 |     0.19 |   30.7 |
| game total o8.5   |    0.78 |    0.49 |     0.41 |     0.16 |   49.5 |
| home win          |    0.48 |    0.49 |     0.39 |     0.19 |   52.6 |
| YRFI              |    0.83 |    0.40 |     0.47 |     0.23 |   50.7 |

**Bias vs 200k truth** is ~0 at every level (max 0.57pp at 4k, itself seed noise; ≤0.08pp at
50k) — confirming the effect is pure sampling noise, no systematic error. The measured SEs track
the `sqrt(p(1-p)/n)` theory line (0.79 / 0.56 / 0.40 / 0.22 pp at p=0.5).

**Runtime per single game-sim:** 52 / 88 / 160 / 486 ms. On a ~15-game slate that's
~0.8s / 1.3s / 2.4s / 7.3s total — all trivial, scaling ~linearly.

### Decision
At 4k the served props carry ~0.5–0.9pp of fixed per-game MC error. Picks are edge-ranked with
strict bars in the 6–12.5pp range, so ~0.8pp of jitter is a meaningful fraction of the decision
threshold and can reorder marginal picks. Raising to **16000** cuts that to ~0.3pp — comfortably
below any threshold, commons and tails alike — for ~2.4s/slate (4× the compute, still trivial).
Beyond 16k the gain is diminishing (50k only reaches ~0.2pp for ~3× more time).

**Shipped:** `SIM_N_SIMS = 16000` (`runner.py:72`). One-line, zero-bias, easily reverted.
