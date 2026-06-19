-- Let multiple projection systems coexist as priors for the same player+season.
--
-- Until now the true-talent prior was single-source: refresh-priors wrote a
-- 'marcel' row and an optional Steamer CSV overwrote it (PK was player_id,season).
-- We now ingest several public projection systems (Steamer / THE BAT X / ATC /
-- ZiPS via refresh-projections) plus our Marcel prior, and materialise a per-metric
-- weighted ensemble as method='blend'. Each source needs its own row, so the
-- method becomes part of the primary key.
ALTER TABLE batter_projection_prior
    DROP CONSTRAINT batter_projection_prior_pkey;

ALTER TABLE batter_projection_prior
    ADD PRIMARY KEY (player_id, season, method);
