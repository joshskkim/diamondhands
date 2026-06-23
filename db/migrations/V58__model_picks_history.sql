-- Model's Picks history: retain bumped picks instead of overwriting them.
-- ============================================================================
-- record-picks used to DELETE the whole slate and re-INSERT the current top-3,
-- so a pick shown in the morning that a better late-game pick out-ranked vanished
-- from both the board and the graded record (survivorship bias). We now reconcile:
-- a pick keeps its row once shown, gets marked active=false/bumped_at when a better
-- pick displaces it pre-game, and freezes once its game starts. Every retained row
-- is still graded and counted — bumped ones tagged so the report card can label them.
--
-- The old PK was (slate_date, rank); that can't hold an active pick and the bumped
-- pick it replaced side by side (and rank is no longer stable across re-runs). Move
-- to a surrogate id, with a stable per-selection identity for the reconcile upsert.
ALTER TABLE model_picks ADD COLUMN id bigserial;
ALTER TABLE model_picks DROP CONSTRAINT model_picks_pkey;
ALTER TABLE model_picks ADD PRIMARY KEY (id);

-- rank is now board order among *active* picks only; bumped/frozen rows may have NULL.
ALTER TABLE model_picks ALTER COLUMN rank DROP NOT NULL;

-- Lifecycle columns.
ALTER TABLE model_picks ADD COLUMN active         boolean     NOT NULL DEFAULT true;
ALTER TABLE model_picks ADD COLUMN first_shown_at timestamptz;   -- when the pick first made the board (locked)
ALTER TABLE model_picks ADD COLUMN bumped_at      timestamptz;   -- when a better pick displaced it (pre-game)

-- Existing rows are latest snapshots; treat their recorded_at as first_shown_at.
UPDATE model_picks SET first_shown_at = recorded_at WHERE first_shown_at IS NULL;

-- One row per selection per slate, the reconcile key. player_id is NULL for game
-- markets, so NULLS NOT DISTINCT (pg15+; we run pg16) makes those rows collide as
-- intended. line is intentionally excluded: a line move keeps the first-shown pick.
CREATE UNIQUE INDEX model_picks_identity
    ON model_picks (slate_date, game_id, market, side, player_id) NULLS NOT DISTINCT;

-- Board read: list active picks first (by rank), then earlier/bumped ones.
CREATE INDEX IF NOT EXISTS idx_model_picks_slate_active
    ON model_picks (slate_date, active, rank);
