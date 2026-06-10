-- Player birth dates (model infra). Sourced from the MLB Stats API /people endpoint
-- (backfill-birthdates command). Intended to feed the Marcel prior's aging curve, but
-- note: with only 2023+ history available, a fitted aging adjustment did NOT beat the
-- age-blind prior out-of-sample (signal is real but swamped by noise at this depth), so
-- the rate adjustment is held pending more seasons / a decision. The column is still
-- useful (age display, filtering, future aging work).
ALTER TABLE players ADD COLUMN IF NOT EXISTS birth_date date;
