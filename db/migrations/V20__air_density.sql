-- Air-density inputs for the v2.3 HR weather model.
-- ============================================================================
-- The HR weather adjustment moves from temperature-only to a physical air-density
-- model (temp + humidity + barometric pressure, referenced to each park's altitude
-- baseline). This adds the stored inputs: stadium altitude (static) and the two
-- new per-game weather fields refresh-weather now fetches from Open-Meteo.

ALTER TABLE stadiums ADD COLUMN altitude_feet INT;            -- park elevation (ft)
ALTER TABLE games   ADD COLUMN relative_humidity_pct NUMERIC(5,2);  -- 0-100
ALTER TABLE games   ADD COLUMN surface_pressure_hpa  NUMERIC(6,1);  -- station pressure (hPa)
