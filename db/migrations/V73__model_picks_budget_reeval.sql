-- Stricter Model's Picks: hard 3-row slate budget + lineup-change re-evaluation.
--
-- bump_reason: why an inactive row left the active board.
--   'displaced' — pre-July-2026 churn (a better late play replaced it); legacy rows
--                 may still be re-promoted by reconcile on transition days.
--   'lineup'    — the game's lineup changed after lock and the pick no longer cleared
--                 the bar; such rows are only ever re-activated by another lineup
--                 re-eval (never by ordinary reconcile).
-- lineup_hash: md5 over both sides' ordered lineup player ids at lock time (missing
--   side = empty segment). record-picks compares it each run — a change is the ONLY
--   re-eval trigger, so market moves can never bump a locked pick.
ALTER TABLE model_picks
    ADD COLUMN IF NOT EXISTS bump_reason text CHECK (bump_reason IN ('displaced', 'lineup')),
    ADD COLUMN IF NOT EXISTS lineup_hash text;

-- Every historical bump predates lineup re-eval: it was displacement.
UPDATE model_picks SET bump_reason = 'displaced' WHERE bumped_at IS NOT NULL;
