-- Stripe subscription / entitlement state, keyed by users.id (one row per user).
-- The app reads the user's tier from here (fast, cacheable) — never from Stripe at
-- request time — and Stripe webhooks keep it in sync. We store only opaque Stripe
-- tokens (customer / subscription ids), never card data, keeping us in PCI SAQ A.
-- See docs/auth-design.md "Payments". Identity stays a thin layer behind users.id.

CREATE TABLE subscriptions (
    user_id                BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    stripe_customer_id     TEXT UNIQUE,          -- created lazily at first checkout
    stripe_subscription_id TEXT UNIQUE,          -- null until a subscription exists
    status                 TEXT,                 -- active / trialing / past_due / canceled / ...
    price_id               TEXT,                 -- which price (monthly vs annual)
    current_period_end     TIMESTAMPTZ,          -- informational ("renews on"); may be null
    cancel_at_period_end   BOOLEAN NOT NULL DEFAULT false,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Webhooks arrive keyed by Stripe customer id, so we look the row up by it.
CREATE INDEX idx_subscriptions_customer ON subscriptions (stripe_customer_id);
