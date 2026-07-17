-- Hand-split xHR → HR base rate (fix HR discrimination vs LHP).
-- ============================================================================
-- The 2026 midseason eval found HR discrimination collapses vs LHP (HR-AUC 0.546
-- vs LHP / 0.603 vs RHP). Root cause: the dominant HR-power input (barrel_rate, 60%
-- of hr_scale) comes from batter_batted_ball keyed (player_id, season) — no
-- handedness split — so a hitter's projected power is identical vs LHP and RHP.
--
-- Fix: split the learned xHR signal by the OPPOSING PITCHER's throwing hand and feed
-- it into the HR base rate in place of the flat barrel term. This also finally wires
-- xHR (V72, previously inert) into projections. Mirrors the V65 barrel_allowed pattern:
-- prior-season constant, populated by re-running refresh-batter-xhr + refresh-skills /
-- refresh-skill-snapshots (no SQL backfill — same as V65).

-- 1. The per-batted-ball corpus gains the opposing pitcher's throwing hand so the xHR
--    scores can be grouped by hand. Populated by refresh-batted-ball-events (delete-
--    then-insert rebuild), NULL on pre-existing rows until that command re-runs.
ALTER TABLE batted_ball_events ADD COLUMN p_throws CHAR(1);

-- 2. Per-batter xHR gains the hand-split rates (+ per-hand sample sizes), written by
--    refresh-batter-xhr. Each hand is EB-regressed toward the batter's OWN overall xHR
--    (not league) so thin per-hand samples fall back to his own power, not the mean.
ALTER TABLE batter_xhr
    ADD COLUMN xhr_vs_l NUMERIC(6,5),
    ADD COLUMN xhr_vs_r NUMERIC(6,5),
    ADD COLUMN bip_vs_l INT,
    ADD COLUMN bip_vs_r INT;

-- 3. Attach the prior-season xHR (overall + per hand) to the skill tables the
--    projection reads, exactly as barrel_rate/barrel_allowed are. NULL until the
--    prior season's batter_xhr is populated, in which case base_rates_from_blend
--    falls back to the barrel/ISO HR basis (pre-lever behaviour).
ALTER TABLE batter_skill
    ADD COLUMN xhr_per_bb NUMERIC(6,5),
    ADD COLUMN xhr_vs_l   NUMERIC(6,5),
    ADD COLUMN xhr_vs_r   NUMERIC(6,5);

-- Mirror onto the point-in-time snapshot table the backtest reads
-- (runner._load_batter_skill_snapshot), so the A/B actually exercises the lever.
-- xHR is prior-season (constant across a season's Monday snapshots), so
-- refresh-skill-snapshots attaches the same value to every snapshot for the season.
ALTER TABLE batter_skill_snapshots
    ADD COLUMN xhr_per_bb NUMERIC(6,5),
    ADD COLUMN xhr_vs_l   NUMERIC(6,5),
    ADD COLUMN xhr_vs_r   NUMERIC(6,5);
