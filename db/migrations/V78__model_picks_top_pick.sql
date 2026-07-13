-- The single "top pick" — a standout among a slate's recorded Model's Picks.
-- ============================================================================
-- The Jul 2026 prop-expansion opened the whole priced board to picks, so the bar
-- tightened to favorite-side value only (model_prob >= 0.55, Analyst 'bet' required).
-- On top of that, the rank-1 pick is flagged a "top pick" when it ALSO clears a higher
-- edge + probability bar (see is_top_pick / TOP_PICK_MIN_* in commands/picks.py) — the
-- one selection we have the most conviction in. Set at record-picks insert time,
-- parallel to `strong`/`rank`; a slate can have picks with no top pick (that's intended).
-- Defaults false so historical rows read as "no top pick", which is accurate.
ALTER TABLE model_picks
    ADD COLUMN top_pick BOOLEAN NOT NULL DEFAULT false;
