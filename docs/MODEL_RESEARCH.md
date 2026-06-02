# Projection model — research & strategy backlog

Where we are (validated on a clean 2023-24 → 2025-H2 holdout, 20.6k rows): a per-batter-game
**XGBoost** model beats the hand-built mechanistic chain on all four binary markets (H≥1, H≥2, HR,
K≥1) and is near-perfectly calibrated (ECE 0.002–0.011). Production serves a `blend` (XGB + a small
mechanistic hedge). The **count/total side** (`expected_hits`, `expected_total_bases`) and the
**team-run** projection are still the weak, untouched mechanistic pieces (hits-MAE never moved).

This doc collects ideas to improve predictions *on top of* the current blend, roughly ordered by
expected ROI given our findings.

## North-star architecture: per-PA outcome distribution → lineup simulation
Today we model four binary markets independently and derive counts mechanically. The principled
unification is to model the **multinomial outcome of a single plate appearance**
(out / K / BB+HBP / 1B / 2B / 3B / HR) given batter, pitcher, park, and matchup, then **Monte-Carlo
simulate the lineup** through the game. From one calibrated PA model you derive *everything*
consistently: P(H≥1), P(H≥2), P(HR), P(K≥1), expected hits/TB, team runs and totals, exact-N props,
and fantasy points — and the simulation naturally handles the variable number of PAs, batting-order
turnover, and (with a reliever model) the SP→bullpen transition. This also replaces the known-weak
Pythagorean team-run proxy (the reason MAE is stuck). Biggest effort, biggest payoff; the regressors
we're building now are a tactical stopgap on the count side.

## Features (highest near-term ROI; feeds the "features+stacking" work)
- **Stacking**: feed the mechanistic model's own per-market probabilities in as XGB features (we
  chose a linear blend over stacking; a meta-model over [mech prob, xgb features] often wins).
- **Quality of contact** at pitch-type granularity: barrel%, hard-hit%, exit velo, xwOBAcon (we
  have season barrel/hard-hit in `batter_skill`, not per pitch type).
- **Plate discipline**: chase% (O-swing), Z-contact%, swing% — strong K/BB signal we don't use.
- **Recent form**: rolling L7/L14 and exponentially-weighted windows (we only have L30); hot/cold.
- **Bullpen / PA context**: later lineup slots face relievers, not the SP — we only model the SP.
  Add expected reliever quality for late PAs (a real, known gap, esp. for K rate).
- **Batter-vs-pitcher history**, umpire strike-zone tendency (K/BB), catcher framing, days rest,
  B2B/travel, and weather when live (we drop it — null historically).

## Model architecture alternatives
- **CatBoost / LightGBM** as XGB swaps: CatBoost is often better-calibrated and handles categoricals
  (team, pitch types, umpire) natively; cheap to A/B against our XGB on the holdout.
- **Player embeddings**: learned batter/pitcher latent vectors (matrix-factorization or a small NN)
  capture identity better than hand features — trees currently "memorize" talent crudely.
- **Multi-task model**: predict all markets jointly from a shared representation (the markets are
  correlated) instead of four independent boosters.
- **Hierarchical / Bayesian partial pooling** of batter & pitcher effects: principled shrinkage for
  thin samples — directly targets the early-season cold-start / OOD fragility that cratered XGB on
  the missing-lineup 2026 test. A robustness play more than an accuracy play.

## Ensembling
- Replace the fixed per-market linear blend with a **learned meta-model** (stacking) over
  [mechanistic prob, XGB prob, CatBoost prob, raw features]. Our clean-sample tuning showed the
  optimal mech weight ≈ 0, so the current value is mostly a robustness hedge — a meta-learner could
  do that hedging adaptively (lean mechanistic only when XGB is out-of-distribution).

## Validation & ops (cheap, high-leverage)
- **Always season-holdout** (train past seasons, test a held-out season) — within-season CV was
  optimistic; the cross-season holdout is the honest test (now standard via `--models-dir`).
- **Calibration + drift monitoring**: track per-market ECE and feature-coverage parity over time
  (the missing-lineup confound would have been caught immediately by a coverage check).
- **Outcome-distribution metrics**: add log-loss and reliability curves to `compare-runs`; for the
  eventual PA-distribution model, score with ranked-probability / multinomial log-loss.

## Suggested sequence
1. Expected hits/TB regressors (in progress) — quick count-side win.
2. Features + stacking (mechanistic probs + plate-discipline + recent-form windows) — likely the
   next real accuracy gain.
3. CatBoost A/B and learned-meta stacking — squeeze + adaptive robustness.
4. Per-PA multinomial model + lineup Monte-Carlo simulation — the unifying rebuild (counts, runs,
   totals, parlays from one calibrated engine); fold in a bullpen/reliever model here.
5. Hierarchical shrinkage / more seasons — robustness, especially early-season.
