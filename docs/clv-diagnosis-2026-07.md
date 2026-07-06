# CLV Diagnosis — July 2026 (diagnose-only sprint)

**Status: skeleton — fill each `⏳ RESULT` from the prod run outputs.**

After ~13 days of live accrual (2026-06-22 → 07-04), `/api/track-record` showed 72 settled
picks at +3.82u (5.3% ROI) but **negative CLV** (clvN=51, clvRate 5.9%, avgClv −0.64pts) —
by our own north star (see `docs/model-roadmap.md`, Phase 0a) the model wasn't beating the
close. Code reading found the headline number sits on measurement artifacts, so before any
model change we verify the metric itself. **No model or pipeline behavior was changed in
this sprint**; it produced the `analyze-picks` command, per-slice CLV in the API/UI, and
this report.

How to produce the inputs (on the box, `/opt/diamond`):

```
./deploy/run-ingester.sh analyze-picks --days 60 --verify --md
```

Paste the sections below. Everything is read-only.

---

## Pre-registered hypotheses (from code reading, before touching prod data)

### H1 — De-vig basis mismatch (confirmed in code; magnitude ⏳)

`model_picks.fair_prob` (bet time) comes from `OddsService.fairShare()`, which de-vigs with
the **best price across all books** on each side. The close is de-vigged from **both sides at
the pick's single book** (`_closing_quote`, `ingester/commands/picks.py` — its own docstring
flags the mismatch). Best-of-books uses the lowest implied on the opposite side, inflating
the pick side's bet-time fair — so `clv = close_fair − fair_prob` carries a **systematic
negative offset** on the order of half the cross-book price dispersion.

`analyze-picks --verify` recomputes CLV with the *same* single-book de-vig at both ends
(`clv_consistent = close_fair_prob − bettime_samebook_fair`).

**⏳ RESULT:** stored mean ______ vs consistent mean ______ ; basis offset ______ [CI].
Verdict: the true CLV read after removing the artifact is ______.

### H2 — Strict positivity + tie mass (confirmed in code; magnitude ⏳)

`TrackRecordService` counts `clv > 0` only; exact ties (0.0000 at 4dp) sit in the
denominator. The UI/API now also reports `clvZeroN`.

**⏳ RESULT:** of clvN=____: >0 ____ / =0 ____ / <0 ____ ; beat-or-tie rate ____ vs strict ____.

### H3 — Missing-CLV selection bias (mechanism confirmed; composition ⏳)

`_closing_quote` matches `line IS NOT DISTINCT FROM <pick line>` — when the book **moves the
line off our number**, no closing quote matches and the pick silently gets NO CLV. Line moves
are the *largest* CLV events, so the stored sample is biased toward stale-line (low-|CLV|)
picks. Taxonomy (from `analyze-picks` coverage section):

- `one_sided` — quote at close but opposite side missing (partial `_closing_quote` return)
- `line_moved` — selection existed at the book pre-pitch, never at our line
- `no_quote` — no snapshot at all (coverage/cadence gap, or pick has no book)

**⏳ RESULT:** of the __ no-CLV picks: one_sided __ / line_moved __ / no_quote __ ;
the no-CLV cohort's record/ROI vs the captured cohort: ______.

### H4 — Timing cohorts (⏳)

Picks lock price at `first_shown_at` (9am daily board vs the */30 12-23 quick loop); the
"close" is the last snapshot before first pitch (up to ~30min stale).

**⏳ RESULT:** morning vs intraday CLV: ______ ; CLV by pick-to-pitch window: ______.

---

## Slice tables (paste from `analyze-picks --days 60 --verify --md`)

### Headline (cross-check vs /api/track-record)

⏳

### By market / by book / by tier / by edge bucket / timing

⏳

### CLV → outcome link (ROI by CLV quartile)

⏳

---

## Cross-reference: calibration overconfidence

Independent of CLV, `/api/accuracy` (30d) shows persistent overconfidence on hits —
hit1plus calibration buckets: predicted 0.65 → actual 0.583 (n=72 bucket), predicted
0.74 → actual 0.634 (n=41). This matches the earlier HR-bucket overconfidence finding
(pred 0.223 vs actual 0.169 — see `hr-eval-gate` memory). Whatever the CLV verdict, the
model's raw probabilities run hot in the upper buckets on hit-family markets.

---

## Honesty guardrails

- n≈51 CLV'd picks (and 72 settled) is **small**; all conclusions provisional. Wilson/normal
  CIs are printed on every slice; anything n<30 is flagged.
- Do not publish a CLV or ROI headline off this sample (`docs/resume-bullets.md` rules).
- The de-vig is proportional at both ends; favorite–longshot bias exists but is
  sign-preserving here (same method both ends) — recorded as a caveat, not a bug.

## Recommended next steps (NOT executed in this sprint — decided by the results above)

1. **If H1 explains most of the negative CLV** → fix the measurement, not the model: store a
   same-book de-vigged `fair_prob` (or a second column) at record time so stored CLV is
   basis-consistent going forward; backfill-recompute historical clv where snapshots allow.
2. **If H3's line_moved cohort is large** → extend `_closing_quote` with a line-move-aware
   fallback (match nearest line at close and translate, or record close at the moved line
   with a push-probability adjustment) so the biggest CLV events stop being censored.
3. **If timing (H4) dominates** → consider re-pricing the board later in the day (picks lock
   at first-shown; a 9am lock vs evening close is a long exposure window).
4. **If genuine negative CLV survives all corrections** → the market-facing bar (edge/EV
   thresholds in `picks.py` / `model-picks.tsx`) needs recalibration before any new model
   lever; pair with the hit-family overconfidence above (shrink upper-bucket probabilities).
