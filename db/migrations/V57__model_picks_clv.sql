-- Phase 0a (model roadmap): CLV (closing-line value) instrumentation on Model's Picks.
-- ============================================================================
-- CLV is the betting north star: positive CLV (your bet's de-vigged probability
-- beat the market's at close) is the single best predictor of long-run profit,
-- and it's measurable in far fewer picks than realized ROI. We already store the
-- bet-time line (price_american/book/fair_prob) on each pick and an append-only
-- price history in odds_snapshots; score-picks now also captures the closing
-- quote and computes CLV.
--
--   clv = close_fair_prob - fair_prob   (positive => we beat the close)
--
-- All four columns stay NULL when no closing quote is found (e.g. line moved off
-- our number, or odds_snapshots lacks the selection near first pitch).
ALTER TABLE model_picks
    ADD COLUMN close_price_american INTEGER,
    ADD COLUMN close_price_decimal  NUMERIC(7,3),
    ADD COLUMN close_fair_prob      NUMERIC(6,4),
    ADD COLUMN clv                  NUMERIC(6,4),
    ADD COLUMN clv_captured_at      TIMESTAMPTZ;
