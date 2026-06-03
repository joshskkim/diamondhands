-- Home-plate umpire data layer (unit U4).
-- Home-plate umpires measurably affect strikeout rates and run scoring via how
-- they call the strike zone. This adds a reference table of umpires with their
-- computed tendencies, plus a per-game home-plate umpire assignment on games.
-- A LATER unit wires these tendencies into the projection model; this is the data layer only.

CREATE TABLE umpires (
    umpire_id        INT PRIMARY KEY,          -- MLBAM person id (officials[].official.id)
    full_name        VARCHAR(100) NOT NULL,
    -- Tendencies, recomputed by `refresh-umpires` from games this ump officiated.
    -- NULL until the umpire clears the minimum-games guard (see refresh_umpires.py).
    k_rate_tendency  NUMERIC(5,4),             -- league-relative K/PA in this ump's games (e.g. 0.22 ~ league avg)
    runs_above_avg   NUMERIC(5,3),             -- (total runs/game in ump's games) - league avg runs/game; +ve = hitter-friendly
    games_sampled    INT NOT NULL DEFAULT 0,   -- # Final games used to compute the tendencies
    updated_at       TIMESTAMPTZ
);

-- Per-game home-plate umpire (nullable: assignments post close to game time, and
-- historical/degraded fetches may leave it NULL). FK so we always upsert the ump first.
ALTER TABLE games ADD COLUMN home_plate_umpire_id INT REFERENCES umpires(umpire_id);

CREATE INDEX idx_games_hp_umpire ON games(home_plate_umpire_id);
