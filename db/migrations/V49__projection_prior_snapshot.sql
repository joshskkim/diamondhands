-- Bank a dated copy of every external projection pull so we accumulate
-- (projection, later-actual) pairs over time.
--
-- batter_projection_prior holds only the CURRENT projection per system. To ever
-- run a leak-free keep/drop test we need the projection as it stood at a point in
-- time (ideally a preseason snapshot) scored against games played AFTER that date.
-- The live FanGraphs API only serves today's numbers and ignores any season param,
-- so the only way to get historical preseason priors in-house is to start saving
-- them now. refresh-projections writes a row here (as_of_date = run date) for each
-- system it fetches; the earliest snapshot of a season becomes the preseason prior.
CREATE TABLE IF NOT EXISTS batter_projection_prior_snapshot (
    player_id   integer     NOT NULL REFERENCES players(id),
    season      integer     NOT NULL,
    method      varchar(20) NOT NULL,
    as_of_date  date        NOT NULL,
    proj_xwoba  numeric(5,4),
    proj_k_rate numeric(5,4),
    proj_iso    numeric(5,4),
    proj_pa     integer,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, season, method, as_of_date)
);
