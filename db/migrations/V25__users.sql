-- User accounts (auth MVP).
-- Numbered V25: main already holds V20–V24 (air_density, batter_batted_ball,
-- park_dimensions, pitcher_projections, nrfi); this is the next free version.
-- The app was read-only with no concept of a user; this adds the identity layer so
-- visitors can sign up and (later) save picks, appear on leaderboards, and sync across
-- devices. Credentials are owned in-app (email + bcrypt hash) — see docs/auth-design.md.
-- Everything user-owned references users.id, keeping identity a swappable layer.

CREATE TABLE users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,        -- stored lower-cased by the app
    handle        TEXT NOT NULL UNIQUE,        -- public display name (leaderboards); never expose email
    password_hash TEXT NOT NULL,               -- BCrypt
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
