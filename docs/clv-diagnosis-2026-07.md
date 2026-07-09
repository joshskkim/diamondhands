# CLV Diagnosis — July 2026 (diagnose-only sprint)

**Status: COMPLETE (2026-07-06).** Prod run: `analyze-picks --days 60 --verify --md`
(image f8fa2da, 85 settled picks 2026-06-22 → 07-05, 60 with CLV).

After ~2 weeks of live accrual, `/api/track-record` showed a healthy ROI but **negative CLV**
(beat-rate ~5%, avgClv −0.76pts) — by our own north star (`docs/model-roadmap.md`, Phase 0a)
the model looked like it was losing to the close. This sprint verified the metric before
reacting to it. **No model or pipeline behavior was changed**; deliverables were the
`analyze-picks` command, per-slice CLV in the API/UI, and this report.

## Verdict in one paragraph

**The negative CLV was entirely a measurement artifact.** Recomputed on a consistent
single-book de-vig at both ends, mean CLV is **+0.04pts, 95% CI [−0.03, +0.11]** — zero —
vs the stored **−0.76pts [−1.29, −0.22]**. The basis offset (+0.79pts [+0.26, +1.33])
matches the stored deficit almost exactly. Deeper: the close price simply *equals* the bet
price for nearly all picks (consistent-basis beat-or-tie = 97%, median exactly 0.0000) —
every pick's first-shown→first-pitch window is <3h, and book lines barely move in that
window. So the model is **not** losing to the close; but as instrumented, CLV also has
almost **no resolution** to tell us whether we're beating it. Two measurement fixes and one
strategic implication follow (see "Next steps").

---

## Hypothesis verdicts

### H1 — De-vig basis mismatch → **CONFIRMED, dominant cause**

Bet-time `fair_prob` = best-of-books de-vig (`OddsService.fairShare`); close = single-book
de-vig (`_closing_quote`). Prod recompute (n=60):

| basis | n | mean | mean95CI | median | beat% | beat/tie% |
|---|---|---|---|---|---|---|
| stored (mixed basis) | 60 | −0.0076 | [−0.0129,−0.0022] | −0.0042 | 5% | 10% |
| consistent (single-book both ends) | 60 | +0.0004 | [−0.0003,+0.0011] | +0.0000 | 7% | 97% |

Basis offset (consistent − stored): **+0.0079 [+0.0026, +0.0133]**. Sign-coherence check
agrees: stored CLV's sign disagrees with the raw same-book price move 18 of 31 times —
the stored sign is noise. Hand-verified picks show it plainly (e.g. ML +188 bet, close
+188 — true CLV 0.0000, stored −0.0033).

### H2 — Strict positivity / tie mass → **confirmed, minor**

Of 60: 3 positive, 3 exact ties, 54 negative on the stored basis (50 of the 54 sit in
[−0.01, 0)). Ties are 5% — real but small next to H1. `clvZeroN` now surfaces them.

### H3 — Missing-CLV composition → **NOT line moves: a run-line mirror bug**

25 of 85 picks carry no CLV. Composition: **24 one_sided, 1 line_moved, 0 no_quote** —
and the one-sided cohort is almost exactly the run-line market (25 of 27 run_line picks
have no CLV). Root cause (structural, found from the data): `_closing_quote` queries both
sides at the **same** `line` value, but a run line is mirrored — home −1.5 / away **+1.5**.
The opposite side never exists at the pick's line, so run-line CLV is censored by
construction. (The 2 run_line picks that did get CLV are degenerate matches: avgClv −0.116,
ignore.) The feared "line moved off our number" cohort is just 1 pick.

The no-CLV cohort out-performs (17-7, +18.7% ROI vs +7.5% captured) — with run-line CLV
fixed, headline CLV coverage goes from 71% to ~99%.

### H4 — Timing cohorts → **confirmed, and it reframes what CLV can measure**

Every one of the 85 picks lands in the **<3h** pick-to-pitch bucket (77 first shown
intraday, 8 morning). Two consequences:

1. The "close" we compare against is minutes-to-a-couple-hours after the bet — in that
   window MLB lines are near-static, which is why consistent-basis CLV is ~exactly zero.
   Our CLV instrument currently measures "did the line move in <3h" — it mostly can't.
2. The morning-vs-intraday ROI split (−36% on n=8 vs +14% on n=77) is noise at this n,
   but the all-<3h finding for even 9am-recorded picks deserves a look at how
   `first_shown_at` is set vs game start times (early slates vs a systematic quirk).

---

## Slices (prod, 60d) — for reference

| slice | n | W-L-P | units | ROI | clvN | avgCLV(stored) |
|---|---|---|---|---|---|---|
| Overall | 85 | 48-37-0 | +7.98 | +9.4% | 60 | −0.0076 |
| moneyline | 31 | 14-17-0 | +1.10 | +3.5% | 31 | −0.0039 |
| run_line | 27 | 18-9-0 | +3.04 | +11.2% | 2 | (censored — mirror bug) |
| total | 27 | 16-11-0 | +3.85 | +14.3% | 27 | −0.0038 |
| draftkings | 31 | 16-15-0 | −0.93 | −3.0% | 22 | −0.0079 |
| fanatics | 27 | 17-10-0 | +3.92 | +14.5% | 14 | −0.0135 |
| fanduel | 27 | 15-12-0 | +4.98 | +18.5% | 24 | −0.0038 |

CLV→ROI quartiles show no relationship (Q1 most-negative-stored-CLV has the best ROI) —
consistent with stored CLV being artifact-dominated noise.

## Honesty guardrails

- n=60 CLV'd / 85 settled is small; every conclusion above is provisional. The one
  finding with a tight CI is the null: consistent-basis CLV ≈ 0 [−0.03, +0.11] pts.
- The +9.4% ROI is **not validated** by CLV (which currently has ~no resolution) and must
  not be published as edge (`docs/resume-bullets.md` rules).
- The calibration overconfidence found alongside (hit1plus: pred 0.65 → actual 0.58,
  pred 0.74 → actual 0.63; /api/accuracy 30d) stands regardless of the CLV verdict.

## Next steps (recommended, NOT executed in this sprint)

1. **Fix the basis (H1):** at record time, also store a same-book de-vigged fair prob
   (new column, keep `fair_prob` as-is for the board) and compute `clv` against it in
   `score-picks`. Optionally backfill-recompute stored clv from `odds_snapshots` (the
   `--verify` query shows it's recoverable).
2. **Fix the run-line mirror (H3):** in `_closing_quote`, look up the opposite side at
   the **negated** line for run_line (and any future spread market). Recovers CLV for
   ~30% of the record.
3. **Give CLV resolution (H4):** the meaningful market move happens before our <3h
   window. The in-flight strict-picks **morning-lock** rework (feat/strict-picks-
   morning-lock: picks locked from the 9am board off predicted lineups, market moves
   can't bump them) solves this as a side effect — once picks lock in the morning, the
   bet→close window spans the whole day and CLV becomes a real discriminator. Fixes 1–2
   should land before or with it so the newly meaningful CLV is measured on the right
   basis. Also audit why even the 8 pre-rework 9am picks all landed <3h pre-pitch.
4. **The real model signal to chase next** is the hit-family upper-bucket overconfidence
   (shrink 0.65–0.75 predictions toward observed ~0.58–0.63) — that's a calibration fix,
   measurable on /api/accuracy without any betting-market dependency.
