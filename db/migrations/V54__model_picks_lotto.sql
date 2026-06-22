-- One extra "Lotto" pick per slate: the single highest-EV play in the longshot
-- region (low model probability + strong value), shown below the disciplined
-- Model's Picks board. Recorded as an extra model_picks row (rank = N+1) flagged
-- here so it's distinguishable from the ranked 1..N picks — kept out of the
-- disciplined hit/miss tally in Recent Results, still graded by score-picks.
ALTER TABLE model_picks ADD COLUMN lotto boolean NOT NULL DEFAULT false;
