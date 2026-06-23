# Diamond — Model Roadmap (post-2026-06-22 gap analysis)

This roadmap turns the multi-agent gap analysis into a concrete, sequenced build plan. Order is
deliberate: **build the measurement instruments before the features**, because every "is it better?"
decision is currently being judged by Brier, which the analysis found is the wrong yardstick (flat on
rare/coin-flip events, market-blind). See `docs/model-explained.md` for the current pipeline.

Guiding verdict:
- **Betting north star → CLV** (closing-line value) + realized fractional-Kelly ROI.
- **Projection north star → log-loss / CRPS** on counts, "sharpness subject to calibration."
- **Brier → kept as a diagnostic guardrail, no longer a feature kill-switch.**
- **The niche to own → sim-native correlation / SGP pricing** (our `game_sim.py` already computes the
  joint game-state; today the pipeline discards it and reads marginals).

Honesty guardrails (per `docs/resume-bullets.md`): metric/eval changes are **craft**, not "accuracy
gains"; don't publish CLV/ROI off a small sample; most past model levers came back Brier-neutral, so
frame builds as honestly-tested hypotheses (nulls included).

Next Flyway migration number: **V56** (V54/V55 used by Phase 0 below; highest before this work was
V53). Check the shared-dev-DB Flyway history before numbering (known collision gotcha).

> **Status (built):** Phase 0 is **done and committed** (Phase 0b = `V54`, Phase 0a = `V55` — the
> two were built 0b-first so the migration numbers are swapped vs. the headings below). Phase 1's
> **engine** is built (`ingester/projection/sgp.py` + retained sim arrays); its serving layer is not.

---

## Phase 0 — Measurement foundation (do first, unblocks everything)

### 0a. CLV instrumentation  *(betting north star)*
**Why first:** it's the only metric the betting literature agrees predicts profit, it's cheap, and it
can only make portfolio claims *more* defensible. Most plumbing already exists.

What we already have:
- `model_picks` (V30) stores `price_american`, `book`, and `recorded_at` — the **bet-time** line.
- `odds_snapshots` (V28) is append-only with `captured_at` per `refresh-odds` run — the **line history**
  (`ingester/ingester/commands/odds.py`, `run_ts`).

Build:
1. **Closing-line capture.** Define "closing" as the last `odds_snapshots` row for a selection before
   `games.game_time` (first pitch). Add a `close-odds` step (or extend `score-picks`) that, per settled
   `model_picks` row, finds the matching closing snapshot by `(game_id, scope, player_id, market, side,
   line, book)` and the max `captured_at < first_pitch`.
2. **Schema (built as `V55`):** added to `model_picks`: `close_price_american INT`,
   `close_price_decimal NUMERIC(7,3)`, `close_fair_prob NUMERIC(6,4)`, `clv NUMERIC(6,4)`,
   `clv_captured_at TIMESTAMPTZ`. (CLV = our de-vigged fair prob at close − fair prob at bet.)
3. **Compute (built):** `cmd_score_picks` finds the closing quote (`_closing_quote`), de-vigs it
   (`_devig_two_way`, mirrors `OddsService`), and writes `clv = close_fair_prob − pick_fair_prob`.
4. **Surface (built):** `TrackRecordService` / `TrackRecordResponse` now expose `clvN`/`clvRate`/
   `avgClv` + web `TrackRecord` type. (Report-card *rendering* is remaining UI polish.)

Honesty: show CLV with a sample-size note + CI; **do not** headline a number under a few hundred settled
picks. `clvN` is returned for exactly this reason.
Effort: **Medium (done).** Files: `ingester/commands/picks.py`, `db/migrations/V55__*.sql`,
`api/.../service/TrackRecordService.java`, `api/.../dto/TrackRecordResponse.java`, report-card UI (pending).

### 0b. Log-loss / CRPS + sharpness  *(projection north star)*
**Why:** Brier is flat exactly on our rare-event markets (HR, 2+); log-loss rewards confident-and-right
(what gets paid at plus-money), CRPS scores the full count distribution we actually produce.

Build:
1. Add to `ingester/ingester/metrics.py`: `log_loss(predicted, actual)` (clip p to [1e-15, 1-1e-15]);
   `crps_count(pmf_or_hist, actual)` for the count/total markets (empirical CRPS = Σ (CDF − 1[actual≤k])²);
   a `sharpness(predicted)` helper (variance/entropy of the predicted-prob distribution, or the
   resolution component of the Brier decomposition).
2. **Schema (built as `V54`):** added `log_loss`/`sharpness` to `daily_accuracy` and `log_loss_*`
   to `backtest_runs`. (CRPS landed as a tested `metrics.py` helper for the *sim count
   distribution* path rather than a `daily_accuracy` column — `daily_accuracy.total_runs` only has
   a point estimate, no pmf to score; wire CRPS in once the sim histogram feeds the accuracy job.)
3. Wired into `ingester/ingester/commands/accuracy.py` (`_upsert_binary`) and `commands/backtest.py`
   so every run emits log-loss alongside Brier; sharpness on the daily snapshots.
4. Surfaced via `AccuracyRepository`/`AccuracyService` + `AccuracyPointDto` + web `AccuracyPoint`.
   (Report-card *rendering* of the new columns is remaining UI polish.)

Honesty: this is an **evaluation** upgrade — frame as statistical craft, not a model accuracy gain.
Effort: **Low.** Files: `ingester/metrics.py`, `ingester/commands/{accuracy,backtest}.py`,
`db/migrations/V55__*.sql`, `AccuracyService.java`.

---

## Phase 1 — The niche: sim-native correlation / SGP pricing

**Why this is the differentiator:** projection-only competitors (THE BAT X / Steamer / ZiPS) have no
sim and structurally cannot price a same-game parlay. Books make their fattest margin on the SGP
correlation tax. Our `game_sim.py` already draws the joint game-state 4,000×; we just throw it away.

Current state (`ingester/ingester/projection/game_sim.py`): `TeamSim` holds per-sim per-slot numpy
arrays (`slot_hits`, `slot_hr`, `slot_tb`, `slot_k`, each `(n_sims, 9)`) and `period_runs[p]`
`(n_sims,)` — i.e. **the joint draws exist in memory** and are then collapsed to marginals in
`_slot_props()`. So correlation is recoverable without changing the simulation, only what we keep.

Build (start narrow — 2-leg correlated pairs, the highest-value case):
1. **Expose the joint.** Add a method to `GameSim` that returns pairwise correlations / joint
   probabilities for selected legs from the retained arrays (e.g. `P(slot_i hit≥1 AND total over L)`,
   `P(player HR AND team total over)`), computed directly as means over the sim axis. No re-simulation.
2. **Persistence decision (pick one):**
   - *(simplest)* recompute on demand: cache the per-game `GameSim` object (or its stacked arrays) in
     Redis/in-memory for the slate day; compute any requested SGP joint on the fly. Good for <~30 games/day.
   - *(durable)* `V56__game_sim_joint.sql`: store a compact joint — either down-sampled per-sim draws
     (e.g. 1,000 of 4,000) as compressed arrays, or a precomputed correlation matrix for the headline
     legs (player props × team total × NRFI/F5).
3. **Pricing layer.** New service that, given two+ legs and their book SGP price, computes the model's
   joint probability, de-vigs the book's implied SGP correlation (reuse `OddsService` de-vig math), and
   surfaces the **correlation edge** (model joint − book-implied joint) and SGP EV.
4. **UI:** a joint-distribution heatmap + "correlated play" card (honesty-safe because it's visually
   explainable). Lives alongside the existing odds/picks boards.

Sequence within phase: (1)+(3) on the recompute-on-demand path first (no schema), prove the edge in
backtest using `odds_snapshots` SGP-equivalent pricing, then decide on durable persistence (2).
Effort: **Hard** (the headline feature). Files: `ingester/projection/game_sim.py`,
`ingester/projection/runner.py`, new `api/.../service/CorrelationService.java` + DTOs, web SGP board,
optional `db/migrations/V56__*.sql`.

---

## Phase 2 — Sim-quality inputs (make the joint trustworthy)

These directly improve the Phase 1 niche by fixing where the sim is weakest (late innings / context),
per the creative expert's "phantom PA" and starter-extrapolation critiques.

### 2a. Arsenal-conditioned times-through-order (TTO) penalty  ✅ BUILT (mechanism, env-gated OFF)
Robust, well-replicated, exogenous (low leak risk). Batter wOBA rises each turn through the order; the
penalty is **larger for fastball-heavy starters** (~−47 wOBA pts by 3rd time vs ~−18 for low-FB arms).
Built: `tto_multipliers`/`_apply_tto_probs`/`_tto_cum_stack` in `game_sim.py`; `_sim_team` tracks
per-sim PAs and selects the 1st/2nd/3rd+ starter matrix per time-through; `simulate_game` threads
`home/away_starter_fb_share`. `constants.TTO_*`, gated `DIAMOND_TTO_ENABLED` (OFF). Default path is
bit-for-bit unchanged. **Enable step (remaining):** wire actual fb share in `runner.py`, re-tune the
run-environment calibration, run a leak-free backtest to set the coefficients. Claim **better
projection**, not betting edge (pitcher props have no demonstrated edge yet — see memory).

### 2b. Bullpen-faced-PA reweighting + blowout/garbage-time realism  ⏸ DEFERRED
Bullpen-faced reweighting is **already in the sim** (`_sim_team` switches to `bullpen_probs` after the
starter's exit). The net-new piece — dampening offense in blowouts (stars pulled, leverage collapses) —
is speculative and calibration-sensitive, and would ship OFF-by-default needing a backtest to enable.
Deferred until there's evidence it's worth the complexity; revisit via run-distribution calibration (CRPS).

### 2c. Playing-time / lineup-slot projection  ✅ BUILT (model + loader; runner wiring is the follow-up)
Underrated for betting (a projection is worthless if the guy sits or bats 8th). Built
`ingester/projection/playing_time.py`: recency-weighted `start_probability` / `compute_playing_time`
(expected PA via `PA_BY_ORDER`) + `project_playing_time(conn, team_id, as_of)` reading recent
`game_lineups` usage; `constants.PT_WINDOW`/`PT_RECENCY_DECAY`. Smoke-tested on the dev DB.
**Follow-up:** wire it into `runner.py` so unconfirmed games project pre-lineup (replacing the flat
4.0-PA deferral) and feed expected PA into the sim — changes live behavior, so do it deliberately.

---

## Phase 3 — Prior craft (defensibility, framed honestly)

Real but lift concentrated on tails / low-sample; likely Brier-neutral. Build for correctness + résumé
craft, **not** as a claimed edge. Don't let these eat the roadmap ahead of Phases 0–1.

### 3a. Aging curve  ✅ BUILT (component-specific, env-gated OFF)
**No new ingestion needed** — `players.birth_date` already exists (V29). Built a component-specific
multiplicative age factor (`aging_factor` in `prior.py`) on the regressed xwOBA (peak ~27) and ISO
(peak ~29, slower decline); K-rate deliberately unaged. `constants.AGING_*`, gated
`DIAMOND_AGING_ENABLED` (OFF). `refresh_priors` loads baseball age (birth_date as of Jul 1) and passes
it through, so enabling is a flag flip. Effect concentrates on age tails. **Enable step:** leak-free
backtest to fit the coefficients (current values are conservative placeholders) + re-tune. A GAM/spline
with survivorship correction is a possible later refinement over the linear-by-peak form shipped here.

### 3b. Empirical-Bayes reliability-weighted shrinkage  🟢 ASSESSED — already effectively in place
On reading the code: the Marcel `regression_pa` constants (`MARCEL_REGRESSION_PA_{XWOBA,K,ISO}`) are
**already out-of-sample-tuned, per-metric shrinkage** — fit on 2023/24→2025 (v2.6.1) precisely so each
metric is "regressed in proportion to how slowly it stabilizes" (K light, ISO heavy). That is fixed-form
empirical Bayes (`regression_pa ≈ σ²_within/σ²_between`), and Marcel already scales the shrinkage by each
player's PA (the dominant reliability signal). A further per-player EB layer needs a new population-
variance calibration step for what the critic predicted is Brier-neutral, redundant-with-3a/2c lift.
**Decision: not built** (avoid speculative redundant code on the live prior); revisit only if a backtest
shows the fixed constants are miscalibrated for a specific cohort.

---

## Phase 4 — Minor-league equivalencies (MLEs)

Fills a real hole: call-ups/rookies currently fall back to league average. Translate MiLB lines to
MLB-equivalent rates via level/park/age multipliers; feed as the prior for players lacking MLB history.
Highest ingestion cost (MiLB stats via MLB Stats API / pybaseball + level factors). Small, noisy slice
of the slate but the softest prop lines.
Effort: **Hard (mostly ingestion).** Files: new `commands/backfill_milb.py`, new MLE table migration,
`projection/prior.py` fallback path.

---

## Explicitly NOT building (dead / redundant / noise — from the analysis)

- **Catcher framing** → same called-strike channel + timing problem as the already-dead umpire-K lever.
- **Regime/talent-change detection** → highest leak risk; the non-leaky part is just aging + EB reworded.
- **Pulled-fly-ball rate as a "new" HR signal** → overlaps the existing barrel term; at most test as a
  refinement of that term, not a new build.
- **Sprint speed for infield hits** → feeds the dead H≥1 market (no exploitable skill).
- **Hot-hand / recency weighting** and **squared-up / swing-length as outcome drivers** → noise.

---

## Suggested execution order (one line)

CLV (0a) → log-loss/CRPS (0b) → correlation/SGP recompute-path (1) → TTO (2a) → bullpen/blowout
realism (2b) → playing-time (2c) → aging (3a) + EB shrinkage (3b) → MLEs (4).
Build the Phase-0 instruments before claiming any feature in Phases 1–4 helps.
