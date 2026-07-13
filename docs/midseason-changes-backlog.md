# Midseason changes — eval-gated backlog (2026)

_Companion to `docs/midseason-eval-2026.md`. Each item is an experiment with a pass/fail
gate; the default outcome is **DROP**._

## How we decide (read first)

Diamond's lever history is deliberately kill-heavy — chase-K, whiff→K, barrel→HR, platoon,
park-hit-geo were all A/B'd and left **OFF**. That is the bar. A change ships only if it
*proves* itself; "seems reasonable" is not a reason to keep code.

- **Out-of-sample split.** Choose/fit any lever on **H1 (Apr–May)**, report the verdict on
  **H2 (Jun–Jul)**. Never tune and report on the same games. Confirm the sign on a second
  split (e.g. leave-July-out) before shipping.
- **Judge.** log-loss primary (sharp on rare events) + Brier; count markets use MAE/CRPS;
  run markets use run-MAE. Any **pick-affecting** change must also keep CLV ≥ 0.
- **Guardrails.** No material regression on *other* markets; sign consistent across splits;
  ≥ ~500 graded rows before trusting a per-market verdict; the in-sample warning stays.
- **Two item types.** *Instruments* (new metrics / coverage) are kept if they give
  trustworthy, non-redundant signal — validated by unit tests + reconciliation, not by moving
  the model. *Tweaks* (model changes) are kept only on OOS metric improvement.

All model-tweak verdicts need the **box** (full season + daily snapshots); the local DB is 3
weeks off one stale snapshot and can only smoke-test plumbing.

## Backlog at a glance

| ID | Item | Type | Cost | Where decided | Keep if |
|----|------|------|------|---------------|---------|
| I1 | Brier decomposition (reliability/resolution/uncertainty) | Instrument | S | local | reconciles: reliability−resolution+uncertainty ≈ Brier |
| I2 | Pitcher-outs CRPS (persist outs pmf) | Instrument | S–M | local | CRPS ranks known cases correctly; agrees w/ MAE direction |
| T5 | Formally drop sim-blend as a prob source | Tweak (drop) | S | box | best w stays 0 on H2 across markets → document + remove sweep from default |
| T3 | Run-line cover-prob calibration | Tweak | M | box | H2 run-line Brier/ECE improves, sign holds |
| T1 | Platoon-aware HR (vs-LHP weak spot) | Tweak | S build / box decide | box | H2 HR log-loss ↓ **on the vs-LHP subset**, no RHP regression |
| T2 | Pitcher walk model, or reduce BB/HR-allowed props | Tweak | M–L | box | walk corr materially ↑ OOS; else demote those cards |
| I4 | NRFI / F5 grading | Instrument | M | local build, box decide | grades vs V53 first-inning cols; calibration sane |
| I3 | Model-vs-closing-line edge metric | Instrument | L | box | reconciles with existing CLV numbers; coverage worth it |
| I5 | TB distribution capture → 2+TB Brier/CRPS | Instrument | M | box | adds signal beyond the count-MAE we already have |
| T4 | Lean pick selection toward K markets | Tweak | S | box | H2 CLV of K-weighted picks ≥ current, hit rate holds |

Recommended order: **I1 → I2 → T5 → T3 → T1 → I4 → T2 → I3 → I5 → T4** (cheap/high-signal
first; expensive or data-limited last).

---

## Instruments

### I1 — Brier decomposition
**Why.** Sharpness alone is thin; a Brier can be bad from *miscalibration* (reliability) or
from *no discrimination* (low resolution). Murphy's decomposition splits it:
`Brier = reliability − resolution + uncertainty`, all readable off the calibration buckets we
already compute. Tells us, per market, whether to fix calibration or fix the signal.
**Change.** Add `brier_decomposition(buckets, base_rate)` to `metrics.py`; print the three
terms next to each market's Brier in `backtest.py`. Pure, no schema.
**Eval / keep.** Unit test: on synthetic buckets the three terms reconstruct the global Brier
(±1e-9). Keep by construction once it reconciles; drop only if redundant with ECE (it isn't —
ECE ≈ reliability, but resolution is the new part).

### I2 — Pitcher-outs CRPS
**Why.** The only market where we already have a genuine integer pmf: `workload` →
`outs_distribution(mu, params)`. CRPS scores the whole outs distribution, not just outs>17.5.
**Change.** Persist the outs pmf (or reconstruct it at grade time from stored `mu_outs` +
`WorkloadParams`) and score `crps_count_mean` over (pmf, actual outs). Add to the pitcher block.
**Eval / keep.** Unit test CRPS on hand-checked pmfs; confirm it orders a sharp-correct vs
flat forecast the expected way. Keep if it adds signal the outs>17.5 Brier misses (it will —
it sees the full shape). Drop if it just tracks the Brier 1:1.
**Note.** This is the *only* market with a stored full pmf — hence CRPS was deferred elsewhere.

### I4 — NRFI / F5 grading
**Why.** The one served market the harness still doesn't grade. `game_sim` already produces
`p_yrfi` / first-inning + F5 period markets; actuals are the V53 first-inning columns on `games`.
**Change.** Capture the period-market probs into `backtest_game_runs` (or a small sibling
table) under `--sim-props`; grade NRFI (Brier/log-loss/calibration) vs first-inning runs, F5
vs the 5-inning score.
**Eval / keep.** Keep if calibration is sane and the market beats its base rate OOS; drop the
*market* from the board (not the grading) if it's a coin flip after a real sample.

### I3 — Model-vs-closing-line edge metric
**Why.** The harness grades vs *actuals* (calibration); money is made beating the *close*. This
scores model prob against closing-line implied prob per market — the true bridge to CLV.
**Change.** Join backtested projections to stored closing odds; per market compute the realized
edge curve (model prob − de-vigged close) and the P&L of betting the model's edge.
**Constraint / cost (L).** Historical closing odds are **partial** (odds coverage is patchy —
BetRivers is the only book with hit+HR+TB; FanDuel is game-markets only). So this can only
cover games/markets with stored closes and may be thin. Scope it to where we have closes.
**Eval / keep.** Keep if it reconciles with the existing `recompute-clv` / `/api/track-record`
numbers on the overlap and coverage is broad enough to be worth the join; otherwise defer —
the picks-flow CLV already answers the money question for recorded picks.

### I5 — Total-bases distribution capture (optional)
**Why.** TB is currently only a count-regression (MAE) because we store just the mean. The sim
draws per-PA outcomes, so it *could* emit a TB histogram → real Brier on 2+TB / 3+TB + CRPS.
**Change.** Capture a per-batter TB pmf during the `--sim-props` sim; grade canonical TB lines.
**Eval / keep.** Keep only if the probabilistic TB score adds signal over the count-MAE we
already have (i.e. TB props would actually be bettable). Lowest priority.

---

## Model tweaks (default = DROP)

### T1 — Platoon-aware HR (chase the vs-LHP weak spot)
**Hypothesis.** Local smoke test: HR discrimination is worse vs LHP (AUC .523) than RHP (.595).
The dormant `DIAMOND_PLATOON_ENABLED` lever may recover it.
**Change.** None to build — flip the env lever and A/B.
**Eval.** `backtest --start 2026-06-01 --end 2026-07-12 --segment-by hand` with the lever
off vs on. **Keep if** H2 HR log-loss ↓ **on the L subset** with no RHP regression and the
sign holds on a second split. **Drop** otherwise (platoon was already killed once league-wide —
this is a *targeted* re-test, not a revival, so the bar is a real vs-LHP win).

### T2 — Pitcher walk model, or reduce BB / HR-allowed props
**Hypothesis.** Smoke test: pitcher BB and HR-allowed carry ~no edge (corr .06–.09, MAE ≈
naive). The walk rate regresses hard to league (`bb_rate_blend`).
**Change (branch A).** Strengthen the walk model (more per-pitcher weight / a walk prior).
**Change (branch B).** If A doesn't clear the bar, **demote** BB and HR-allowed prop cards so
we don't surface no-edge markets as if they're signal.
**Eval.** H2 walk-count corr + BB>1.5 Brier, before/after. **Keep A** only if corr rises
materially OOS; **else keep B** (reduce) — a no-edge market shown as a pick is a negative.

### T3 — Run-line cover-prob calibration
**Hypothesis.** Smoke test: run-line Brier .2268 vs .2231 base, ECE .055 — mildly
miscalibrated; the sim margin distribution is likely too wide/narrow.
**Change.** Either calibrate `p_home_cover_1_5` (isotonic, like `--calibrate` for batter
markets) or check/adjust the sim's run variance.
**Eval.** H2 run-line Brier + ECE before/after. **Keep if** both improve and the fix
generalizes (isn't overfit to H1's buckets); **drop** if it just memorizes H1.

### T4 — Lean pick selection toward K markets
**Hypothesis.** K is the strongest edge everywhere (pitcher-K corr .406; K≥1 the only batter
market clearly beating baseline). Pick selection may under-weight it.
**Change.** Bias the candidate-pool ranking toward K-family markets (pick-layer, not the model).
**Eval.** **Pick-affecting → CLV is the judge.** H2 CLV + hit rate of the K-weighted board vs
current. **Keep if** CLV ≥ current and hit rate holds; **drop** if it just concentrates variance.

### T5 — Formally drop sim-blend as a probability source
**Hypothesis.** The `--sim-props` weight sweep returns best w = 0 for every market, again
(local + all prior runs). The sim doesn't beat the closed-form board.
**Change.** Confirm on the box H2, then **document the kill** and stop presenting the sweep as
a live tuning knob (keep the sim for explainability / correlation / SGP only).
**Eval.** **Keep the sim-as-prob idea only if** best w > 0 with an OOS Brier win on H2 for some
market. Given the evidence, the expected outcome is a clean, documented **drop**.

---

## Instrument build status (I1–I5 DONE, 2026-07-13)

All five instruments built, unit-tested (`tests/test_backtest_metrics.py`, 629 green), and
validated end-to-end on the local window (2026-06-22→07-12, stale 06-22 snapshot — directional
only). Migrations V79 (pitcher/run-line, prior), **V80** (NRFI), **V81** (sim TB pmf).

- **I1 Brier decomposition** — `metrics.brier_decomposition`; prints reliab/resol/uncert per
  market. Reconciles to Brier. Finding: HR resolution ≈ 0.001 (barely discriminates); K has the
  highest resolution (0.008) — quantifies that K is the real signal and HR is near-noise.
- **I2 Pitcher-outs CRPS** — persists the outs pmf (`workload.outs_pmf_list`); scores the whole
  distribution. **Caught + fixed a real bug in `crps_count`**: it truncated the sum at the pmf
  support, so a shorter-support forecast scored unfairly well. After the fix the model's outs
  distribution (CRPS 2.15) cleanly beats a naive point forecast (3.01). **Keep.**
- **I4 NRFI grading** — V80; closed-form `p_yrfi` graded vs V53 first-inning actuals. Brier
  0.2437 vs 0.2500 baseline, ECE 0.043 — a small real edge over the base rate. **Keep.** (F5
  deferred — no first-5 actuals stored.)
- **I5 TB distribution** — V81; sim `tb_hist` → 2+TB Brier (0.2293 vs 0.2304 baseline — thin)
  + TB CRPS. Instrument sound; the *market's* value is marginal, box decides.
- **I3 Edge-vs-close** (`--vs-close`, batter hit) — reuses `_devig_two_way`; closing line from
  `odds_snapshots`. Finding on 317 rows: model runs **+0.057 hot vs market** and does NOT beat
  the close (model log-loss 0.6463 vs market 0.6448). Coverage is the constraint — only 23/270
  local games have odds; box (daily refresh-odds) is where this earns its keep. Batter-hit only
  for now; other markets are mechanical to add once box coverage justifies it.

## Tweak A/B harness — one command each (wired 2026-07-13)

All five tweaks are now a single command on the box (fit on H1, validate on H2). Verdicts are
still box-gated; the local run only proves the plumbing. **Default stays the current behavior**
— every lever is OFF/no-op unless the env/flag is set.

- **T1 platoon (zero code).** `_resolve_matchup` already honors the lever on the backtest path:
  ```
  DIAMOND_PLATOON_ENABLED=1 uv run python main.py backtest --start 2026-06-01 --end 2026-07-12 --segment-by hand
  ```
  Keep iff H2 HR log-loss ↓ **on the L subset** vs the lever-off run, no RHP regression.
- **T2 walk/K priors (env-tunable).** `DIAMOND_BB_RATE_PRIOR_BF` / `DIAMOND_K_RATE_PRIOR_BF`
  (defaults 120 / 100; LOWER = more per-pitcher weight). Sweep on H2:
  ```
  DIAMOND_BB_RATE_PRIOR_BF=60 uv run python main.py backtest --start 2026-06-01 --end 2026-07-12
  ```
  Keep iff pitcher-BB corr/MAE improves OOS; else the "reduce" branch (demote BB/HR-allowed cards).
- **T3 run-line calibration (fit/apply).** Fit on H1, apply to H2 — the harness prints raw vs
  calibrated Brier/ECE:
  ```
  uv run python main.py backtest --start 2026-04-01 --end 2026-05-31 --sim-props --fit-runline-cal models/rl_cal.json
  uv run python main.py backtest --start 2026-06-01 --end 2026-07-12 --sim-props --runline-cal models/rl_cal.json
  ```
  Keep iff calibrated Brier+ECE beat raw OOS. (Local 3-wk split: it OVERFIT — calibrated worse —
  so the local lean is DROP; box sample decides.)
- **T4 K-lean picks (OFF-by-default lever).** `DIAMOND_K_MARKET_SCORE_BONUS` (default 0.0 = no
  change) adds a ranking bonus to `pitcher_k`. **CLV-judged, not the backtest** — enable in the
  nightly picks env, then compare forward CLV/hit-rate over ~2–3 wks. Keep iff CLV ≥ current.
- **T5 sim-blend (zero code).** The `--sim-props` sweep already prints best-w per market; every
  run so far returns w=0. Confirm on H2, then document the kill (keep the sim for explainability
  /correlation only).

## Execution notes
- Instruments I1/I2 and the T5 confirmation are **buildable + unit-testable locally now**;
  their model-impact verdicts (and every other tweak) wait on the box run from
  `docs/midseason-eval-2026.md`.
- Every kept/dropped item updates the **add/reduce/kill table** in `docs/midseason-eval-2026.md`
  and MEMORY, with the H2 numbers that decided it.
