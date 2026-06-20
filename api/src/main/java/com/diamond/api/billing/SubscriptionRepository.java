package com.diamond.api.billing;

import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;

/** Subscription/entitlement rows in {@code subscriptions}, keyed by {@code users.id}. */
@Repository
public class SubscriptionRepository {

    private final JdbcTemplate jdbc;

    public SubscriptionRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** A user is entitled ("Pro") while their subscription is active or trialing. */
    private static final String ACTIVE_STATUSES = "('active', 'trialing')";

    public boolean isPro(long userId) {
        Boolean pro = jdbc.queryForObject(
            "SELECT EXISTS(SELECT 1 FROM subscriptions WHERE user_id = ? "
                + "AND status IN " + ACTIVE_STATUSES + ")",
            Boolean.class, userId);
        return Boolean.TRUE.equals(pro);
    }

    public Optional<String> findCustomerId(long userId) {
        return one("SELECT stripe_customer_id FROM subscriptions WHERE user_id = ?", userId);
    }

    public Optional<Long> findUserIdByCustomer(String customerId) {
        try {
            return Optional.ofNullable(jdbc.queryForObject(
                "SELECT user_id FROM subscriptions WHERE stripe_customer_id = ?",
                Long.class, customerId));
        } catch (EmptyResultDataAccessException e) {
            return Optional.empty();
        }
    }

    /** Link a freshly-created Stripe customer to a user (idempotent on user_id). */
    public void linkCustomer(long userId, String customerId) {
        jdbc.update("""
            INSERT INTO subscriptions (user_id, stripe_customer_id, updated_at)
            VALUES (?, ?, now())
            ON CONFLICT (user_id) DO UPDATE SET
                stripe_customer_id = EXCLUDED.stripe_customer_id,
                updated_at = now()
            """, userId, customerId);
    }

    /** Sync subscription state from a Stripe webhook, located by customer id. */
    public void syncByCustomer(String customerId, String subscriptionId, String status,
                               String priceId, Instant currentPeriodEnd, boolean cancelAtPeriodEnd) {
        Timestamp periodEnd = currentPeriodEnd == null ? null : Timestamp.from(currentPeriodEnd);
        jdbc.update("""
            UPDATE subscriptions SET
                stripe_subscription_id = ?,
                status = ?,
                price_id = ?,
                current_period_end = ?,
                cancel_at_period_end = ?,
                updated_at = now()
            WHERE stripe_customer_id = ?
            """, subscriptionId, status, priceId, periodEnd, cancelAtPeriodEnd, customerId);
    }

    private Optional<String> one(String sql, Object arg) {
        try {
            return Optional.ofNullable(jdbc.queryForObject(sql, String.class, arg));
        } catch (EmptyResultDataAccessException e) {
            return Optional.empty();
        }
    }
}
