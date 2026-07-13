# Midseason model evaluation — 2026

_Opened 2026-07-12 (season ~halfway). Owner: model. Status: harness extended (this branch);
results pending a box run._

## What this is

An honest, leak-free read on how the projection model is doing on **this season's** games:
what it predicts well, what's weak, and — via A/B on a held-out half — what to add or reduce.
The method is **walk-forward backtesting (retrodiction)**: for each past date the harness
rebuilds every player's skill profile *as of the day before* (`batter_skill_snapshots`,
`pitcher_starts` strictly-before the snapshot), projects, and grades against actuals. It never
uses anything the model couldn't have known at the time.

Two honesty guardrails govern everything below:

1. **Leak-free as-of.** No live weather (neutralized + tagged `WEATHER_SKIPPED`), snapshot
   skills only, no full-season bullpen aggregate on a historical game.
2. **Never tune and report on the same games.** Hindsight overfits. Fit / choose any lever on
   **H1 (Apr–May)** and validate on **H2 (Jun–Jul)** (or leave-one-month-out). The scorer
   already prints an in-sample warning on the sim-blend sweep — hold every tweak to that bar.

The eval has two halves: **(A) model accuracy** (calibration/discrimination, below) and
**(B) money** (CLV/ROI of actually-recorded picks — see the last section).

## Coverage — what the harness grades (after this branch)

| Market | Metric(s) | Source of actuals | Notes |
|---|---|---|---|
| Batter H≥1 / H≥2 / HR / K≥1 | Brier, log-loss, ROC/PR-AUC, lift, calibration, **ECE, sharpness** | `player_game_stats` | ECE/sharpness newly surfaced (Phase 1) |
| Batter **total bases** | count MAE, corr, bias | `player_game_stats.total_bases` | count-regression (only a mean is stored — no Brier/CRPS) |
| **Pitcher props** — outs/K/BB/H/HR/ER≈R/BF | count MAE/corr/bias + **Brier/log-loss** on K>5.5, outs>17.5, BB>1.5 | `pitcher_starts` (V31) | line Brier from the workload `p_*` ladders; ER graded vs earned runs (approx) |
| Game **run totals** | run MAE, corr, baseline | final score | pre-existing |
| **Run line** — P(home covers −1.5) | Brier, log-loss, ECE | final margin | `--sim-props` only (needs the sim margin) |

Still ungraded / deferred: NRFI/F5 (grade vs V53 first-inning cols — not built here), and CRPS
on any market (no full per-count pmf is persisted; feasible later for outs via
`outs_distribution`, and for TB/K if the sim captures a count histogram).

## Runbook (run on the box — it has the 2026 snapshots)

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21   # (api only; not needed for ingester)
cd ingester

# 0. Sanity: confirm 2026 coverage before trusting any number.
#    games w/ final scores, player_game_stats, pitcher_starts, and DISTINCT
#    batter_skill_snapshots.as_of_date should all span 2026-04 → today.

# 1. Full-season baseline scorecard (the "before" reference).
uv run python main.py backtest --start 2026-04-01 --end 2026-07-12 --sim-props --csv

# 2. Held-out halves for the tweak loop (fit on H1, validate on H2).
uv run python main.py backtest --start 2026-04-01 --end 2026-05-31 --sim-props   # H1
uv run python main.py backtest --start 2026-06-01 --end 2026-07-12 --sim-props   # H2

# 3. Segmentation — localize strength/weakness (repeat per dimension).
for S in month slot home hand confidence; do
  uv run python main.py backtest --start 2026-04-01 --end 2026-07-12 --segment-by $S
done

# 4. A/B a candidate lever: baseline vs lever-on on the SAME held-out H2 range,
#    compare Brier/log-loss deltas. Examples (flags/env from constants.py):
uv run python main.py backtest --start 2026-06-01 --end 2026-07-12 --team-defense
uv run python main.py backtest --start 2026-06-01 --end 2026-07-12 --calibrate
DIAMOND_SIM_PROP_BLEND_WEIGHT_HR=<w> uv run python main.py backtest ... --sim-props
```

`compare-runs --runs a,b,c` gives a side-by-side of Brier + calibration across saved
`backtest_runs` ids; every run above persists one.

## Copy-paste box script (v2 — all tweaks + instruments wired)

Prereq: deploy this branch + apply migrations on the box, then run from the ingester dir (or
`docker compose exec ingester bash`). The sim-props runs are slow (16k sims/game) — use
`tmux`/`nohup`. Everything tees to one log; paste that log back.

```bash
# --- prereqs ---
git fetch && git checkout feat/expand-picks-markets && git pull
docker compose run --rm flyway            # applies V79 / V80 / V81

LOG=/tmp/midseason_eval.log; : > "$LOG"

# --- Step 0: coverage — PASTE THIS FIRST so we can set the H1/H2 split ---
psql "$DATABASE_URL" -c "
  SELECT 'games final'   , count(*) FROM games WHERE game_date>='2026-04-01' AND home_score IS NOT NULL
  UNION ALL SELECT 'pitcher_starts', count(*) FROM pitcher_starts WHERE game_date>='2026-04-01'
  UNION ALL SELECT 'snapshot days' , count(distinct as_of_date) FROM batter_skill_snapshots WHERE as_of_date>='2026-04-01'
  UNION ALL SELECT 'games w/ odds' , count(distinct game_id) FROM odds_snapshots os JOIN games g ON g.id=os.game_id WHERE g.game_date>='2026-04-01'
  UNION ALL SELECT 'games w/ 1st-inn', count(*) FROM games WHERE game_date>='2026-04-01' AND home_score_1st IS NOT NULL;
  SELECT min(game_date), max(game_date) FROM games WHERE game_date>='2026-04-01' AND home_score IS NOT NULL;"

# If April/May are thin, tell me and we re-cut the split. Default below: H1=Apr–May, H2=Jun–Jul.

# --- Step 1: H1 baseline + FIT the run-line calibration map (T3) ---
{ echo '### H1 2026-04-01..05-31'; uv run python main.py backtest \
    --start 2026-04-01 --end 2026-05-31 --sim-props --fit-runline-cal models/rl_cal.json; } 2>&1 | tee -a "$LOG"

# --- Step 2: H2 baseline + APPLY T3 map + edge-vs-close (I3). All instruments print here. ---
{ echo '### H2 2026-06-01..07-13'; uv run python main.py backtest \
    --start 2026-06-01 --end 2026-07-13 --sim-props --runline-cal models/rl_cal.json --vs-close; } 2>&1 | tee -a "$LOG"

# --- Step 3: segmentation (full season, fast — no sim needed) ---
for S in hand slot month confidence; do
  { echo "### segment $S"; uv run python main.py backtest \
      --start 2026-04-01 --end 2026-07-13 --segment-by $S; } 2>&1 | tee -a "$LOG"
done

# --- Step 4: T1 platoon A/B on H2 (compare the 'hand' tables) ---
{ echo '### T1 platoon OFF'; uv run python main.py backtest \
    --start 2026-06-01 --end 2026-07-13 --segment-by hand; } 2>&1 | tee -a "$LOG"
{ echo '### T1 platoon ON'; DIAMOND_PLATOON_ENABLED=1 uv run python main.py backtest \
    --start 2026-06-01 --end 2026-07-13 --segment-by hand; } 2>&1 | tee -a "$LOG"

# --- Step 5: T2 walk-prior sweep on H2 (compare the pitcher BB row) ---
for BB in 120 60 30; do
  { echo "### T2 BB_prior=$BB"; DIAMOND_BB_RATE_PRIOR_BF=$BB uv run python main.py backtest \
      --start 2026-06-01 --end 2026-07-13; } 2>&1 | tee -a "$LOG"
done

echo "DONE — paste $LOG back (or: gzip $LOG)"
```

Then the **money half** (separate; needs the API up):

```bash
uv run python main.py recompute-clv --season 2026     # check --help for exact flags
curl -s localhost:8080/api/track-record | jq .        # clvN / clvRate / avgClv
```

**T4 (K-lean) and T5 (sim-blend)** need no extra runs: T5's best-w prints inside the Step 1/2
`--sim-props` sweep; T4 is CLV-judged — set `DIAMOND_K_MARKET_SCORE_BONUS=0.03` in the nightly
picks env and compare forward CLV over ~2–3 weeks (don't decide it from the backtest).

Paste the log + the Step-0 coverage + the track-record JSON, and I'll fill the decision tables
below and kill/keep each lever.

## RESULTS — run 2026-07-13 on a prod-DB pull

Reality check: **no full season exists** — prod (and local) retain only **2026-06-19 → 07-12**
(329 games, ~24 days; separate data-retention issue to chase). Pulled the 172 MB prod DB to a
local `diamond_prod`, applied V79–V81, ran there. Snapshots are **weekly** (Jun 15/22/29, Jul 6)
→ ≤7-day leak-free staleness — trustworthy, unlike the local dev DB's single 3-week-stale one.
Sample is a ~24-day window, so tweak verdicts are directional; instruments pool all 325 games.

### (A) Model accuracy — full window (325 games)
| Market | Brier | baseline | log-loss | ROC-AUC | notes |
|---|---|---|---|---|---|
| H≥1 | 0.2368 | 0.2369 | 0.667 | 0.548 | ≈ market (no edge) |
| HR | 0.1094 | 0.1104 | 0.375 | 0.587 | resolution ≈ 0 — barely discriminates |
| K≥1 | 0.2324 | 0.2382 | 0.657 | 0.603 | **the model's one real edge** |
| Total bases | MAE 1.347 | mean-MAE 1.393 | — | corr +0.134 | bias −0.08; 2+TB Brier 0.229 vs 0.231 |
| Pitcher K>5.5 | 0.218 | ~0.239 | 0.624 | — | beats base ~9%; K corr 0.36 |
| Pitcher outs>17.5 | 0.227 | ~0.240 | 0.646 | — | CRPS 2.06 vs naive-point 3.03 |
| Pitcher BB | MAE 1.096 | 1.105 | — | **corr −0.02** | league-flat expected_bb → no edge |
| Run line (home −1.5) | 0.2205 | 0.2222 | 0.632 | — | **well-calibrated, ECE 0.014** |
| NRFI (YRFI) | 0.2442 | 0.2500 | 0.682 | — | small real edge, ECE 0.058 |
| Run totals | MAE 3.658 | 3.736 | — | corr +0.20 | |

Brier decomposition confirms the story: **K resolution 0.006 (highest), HR/H1 resolution ~0.001**
— the model discriminates K, barely discriminates HR/hits; all markets are well-calibrated
(reliability ~0.001–0.002).

### Segmentation
- **hand:** HR-AUC **0.546 vs LHP** vs **0.603 vs RHP** — real, consistent HR weakness against lefties.
- **slot:** H≥1 Brier degrades down the order (0.219 leadoff → 0.253 at #8), as expected.

### (B) Money — CLV on recorded picks (115 picks, 112 graded)
avg CLV **≈ 0.000** (moneyline −0.001, total +0.000, run_line +0.001) — the model is **roughly
market-efficient**: neither beats nor loses to the close. Picks are almost all game markets;
props barely appear. This agrees with **I3 edge-vs-close** (4,075 hit-rows: model log-loss 0.675
> market 0.666; model-favored rows realize 0.593 vs fair 0.591 — no edge). Consistent with the
flat avgClv in `docs/clv-diagnosis-2026-07.md`.

## Add / reduce / kill decisions (OOS where a split applies)

| Lever | Result | Decision | Rationale |
|---|---|---|---|
| **T1** platoon (vs-LHP HR) | L HR-AUC 0.546 → 0.547, HR Brier unchanged | **DROP** | zero effect; the vs-LHP gap is real but platoon isn't the fix |
| **T2** walk prior 120→60→30 | BB corr −0.02 unchanged; BB>1.5 Brier 0.247→0.252 (worse) | **DROP tune → REDUCE** | expected_bb is league-flat by construction; demote BB-allowed props (structural fix = thread `bb_rate` into `pitcher_line_from_lineup`) |
| **T3** run-line calibration | H2 raw Brier 0.228 (ECE 0.016) → calibrated 0.237 (ECE 0.094) | **DROP** | raw is already calibrated; the H1 map overfits |
| **T5** sim-blend weight | best-w = 0.00 on every market | **DROP** | sim never beats the closed-form; keep sim for explainability/correlation only |
| **T4** K-lean picks | not backtest-decidable; K is the validated edge | **FORWARD TEST** | set `DIAMOND_K_MARKET_SCORE_BONUS` in nightly picks, judge on forward CLV |

## Prior-lever audit (2026-07-13) — the most actionable finding

Re-checked the *existing* levers on the same trustworthy pull. Two production problems surfaced,
worth more than any of the tweaks above:

| Lever | Backtest A/B | Finding | Action |
|---|---|---|---|
| **L4 pitcher Marcel prior** (ships ON) | prior OFF vs ON → **byte-identical** | `pitcher_projection_prior` = **0 rows in prod**. The proven lever (K −14%/BB −9%) is **INERT in production** — its nightly refresh never populates the table. Matches the long-standing "verify prod is populated" warning. | **Fix `refresh-pitcher-priors` / `refresh-priors` on the box** |
| **batter prior + xHR** | — | `batter_projection_prior` = 0, `batter_xhr` = 0 → batter prior + the xHR HR-ranker are **also inert** (explains the HR gate's "0 rows with a prior-season profile") | same refresh-jobs investigation |
| **L5 hit de-luck** (ships ON, W=0.5) | W=0 vs 0.5 → no measurable change | no effect on the graded markets here; may not touch the graded path (pitcher `expected_h` comes from the lineup, not the pitcher's de-lucked rate) | verify it's on a graded path; low urgency |
| **team-defense** (flag-gated, `--team-defense`) | OFF vs ON → H≥1 0.2368 → **0.2360**, TB MAE 1.347 → **1.331** | real, positive, reproduces the prior "−0.4% hit" result on trustworthy data | **ship candidate — enable by default** |

That team-defense moved the numbers proves the backtest *does* honor runtime levers, so L4's zero
effect is specifically its **empty data table**, not a harness gap. Levers 1/2/3 (barrel→HR,
whiff→K, chase→K), spray, park-geo were left alone — already A/B-killed, default OFF, and 24 days
is not "new input."

**Net:** an entirely kill-heavy outcome, consistent with Diamond's lever history. The one
positive to act on is **K** (the model's real, well-calibrated edge → the T4 forward test). The
one real weakness worth a *new* build is **HR discrimination vs LHP** (platoon doesn't fix it —
needs point-in-time platoon snapshots or an LHP-specific HR feature). Instruments I1–I5 all
worked and produced trustworthy reads (I2 also fixed a `crps_count` tail-truncation bug).

Known-dead levers stay OFF (chase-K, pitcher-whiff→K, pitcher-barrel→HR, platoon, park-hit-geo).

## Local smoke test — 2026-06-22 → 07-12 (LOW FIDELITY, not the verdict)

Ran end-to-end on the local dev DB, which holds only ~3 weeks of 2026 games and **3 weekly
snapshots** — so every game is projected from the **06-22 snapshot** (up to 3 weeks stale).
This validates the harness and hints at direction; it **understates model quality** and the
segment splits are noisy. Real numbers await the box (full season + daily snapshots).

- **Batter Brier (n≈4,700):** H≥1 0.2378 (base .2373 — at baseline), HR 0.1093 (base .1100),
  K≥1 0.2284 (base .2377 — the clearest edge). Discrimination: HR-AUC .573, K-AUC .631.
- **Total bases:** MAE 1.342 vs 1.382 naive (~3% better), bias −0.07 (well-centered).
- **Pitcher props (465 starts):** K is the signal — MAE 1.96 vs 2.09, corr .406; outs/BF barely
  beat naive; **BB, HR-allowed sit AT baseline (corr ~.06–.09 — no edge)**; ER≈R corr .11.
  Line Brier: K>5.5 .2319, outs>17.5 .2431, BB>1.5 .2506.
- **Run line:** Brier .2268 vs .2231 base (slightly worse), ECE .055 — mildly miscalibrated.
- **Sim-blend sweep:** best w=0 for all markets → sim doesn't beat closed-form (keep sim for
  explainability/correlation only).
- **Segmentation (slot):** H≥1 Brier degrades down the order (.216 leadoff → .259 at #8).
  **(hand):** HR-AUC .595 vs RHP but only **.523 vs LHP** — a real weak spot to chase.

## Implementation status (this branch)

Harness extensions landed + unit-tested (`tests/test_backtest_metrics.py`); full suite green,
ruff clean. **Not yet run end-to-end against data** — Docker was down locally; the numbers
above must come from a box run.

- Phase 1 — ECE + sharpness surfaced in `backtest.py` output.
- Phase 2a — total-bases count-regression score.
- Phase 2b — `V79` `backtest_pitcher_projections`; persisted in `runner._project_game_backtest`
  (leak-free, opener-skip mirrored); graded vs `pitcher_starts`.
- Phase 2c — `V79` run-line columns on `backtest_game_runs`; sim cover prob captured + graded.
- Phase 3 — `--segment-by {month,slot,home,hand,confidence}`.
