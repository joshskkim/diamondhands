-- CLV measurement fixes (2026-07 diagnosis, docs/clv-diagnosis-2026-07.md).
-- ============================================================================
-- Stored clv was computed on a MIXED de-vig basis: fair_prob (bet time) comes from
-- OddsService's best-of-books de-vig, while close_fair_prob is a single-book de-vig.
-- Best-of-books inflates the bet-time fair, so every clv carried a systematic
-- negative offset (~-0.8 prob pts) — the "model loses to the close" scare was the
-- instrument, not the model.
--
-- score-picks now de-vigs BOTH ends at the pick's own book: fair_prob_book is the
-- same-book fair prob at the price lock (first_shown_at), and
--
--   clv = close_fair_prob - fair_prob_book   (same basis both ends)
--
-- fair_prob (best-of-books) stays untouched — it is the board's edge basis.
-- Historical rows are recomputed by the one-shot `recompute-clv` command (the
-- inputs live in append-only odds_snapshots). NULL = no same-book two-sided quote
-- at the lock (or the row predates scoring).
ALTER TABLE model_picks
    ADD COLUMN fair_prob_book NUMERIC(6,4);
