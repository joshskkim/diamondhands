-- Marcel-style multi-year true-talent prior per batter (model v2.4.0).
--
-- refresh-priors computes a projected baseline from each player's prior three
-- seasons (recency weights 5/4/3, PA-weighted, regressed to league). refresh-
-- skills then regresses the player's in-season rates toward THIS prior instead
-- of the flat league mean, so a thin in-season sample reverts to the player's
-- established skill rather than the league average.
--
-- `season` is the TARGET season the prior projects (e.g. a 2026 row is built
-- from 2023/2024/2025). `proj_pa` is the recency-weighted PA behind the prior
-- (a reliability proxy, not a playing-time projection). `method` tags the
-- source so a licensed projection set (Steamer/ZiPS/THE BAT) can be dropped in
-- later behind the same table without a schema change.
CREATE TABLE IF NOT EXISTS batter_projection_prior (
    player_id   integer     NOT NULL REFERENCES players(id),
    season      integer     NOT NULL,
    proj_xwoba  numeric(5,4),
    proj_k_rate numeric(5,4),
    proj_iso    numeric(5,4),
    proj_pa     integer,
    method      varchar(20) NOT NULL DEFAULT 'marcel',
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, season)
);
