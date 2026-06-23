-- Phase 0b (model roadmap): demote Brier to a diagnostic, add proper-scoring metrics.
-- ============================================================================
-- Brier is nearly flat on the rare-event markets (HR, 2+ hits) and on near-coin-
-- flip props, so it can't distinguish the models we care about. We add:
--   log_loss  — strictly-proper cross-entropy that rewards sharp, confident-and-
--               right probabilities (what gets paid at plus money).
--   sharpness — variance of the predicted probabilities (decisiveness). Reported
--               WITH ece so we can read "sharpness subject to calibration"
--               (Gneiting et al.); a base-rate predictor is calibratable yet useless.
-- Populated for the binary markets only (NULL for total_runs), mirroring brier/ece.
ALTER TABLE daily_accuracy
    ADD COLUMN log_loss  NUMERIC(7,5),   -- binary cross-entropy; NULL for total_runs
    ADD COLUMN sharpness NUMERIC(7,5);   -- variance of predicted probs; NULL for total_runs

ALTER TABLE backtest_runs
    ADD COLUMN log_loss_hit1plus  NUMERIC(7,5),
    ADD COLUMN log_loss_hit2plus  NUMERIC(7,5),
    ADD COLUMN log_loss_hr        NUMERIC(7,5),
    ADD COLUMN log_loss_k1plus    NUMERIC(7,5);
