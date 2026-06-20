package com.diamond.api.metrics;

import com.diamond.api.billing.StripeProperties;
import com.stripe.exception.StripeException;
import com.stripe.model.Price;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Product / business metrics as Micrometer gauges, scraped by Prometheus alongside the
 * technical metrics and charted on the "Diamond — Business" Grafana board. Values are
 * refreshed on a timer (cheap COUNTs + cached Stripe price lookups) rather than computed
 * per scrape, and each refresh keeps the last good value on a transient DB/Stripe blip.
 *
 * Exposed (Prometheus names): diamond_users, diamond_subscriptions_active,
 * diamond_subscriptions_customers, diamond_mrr_usd.
 */
@Component
public class BusinessMetrics {

    private static final Logger log = LoggerFactory.getLogger(BusinessMetrics.class);

    private final JdbcTemplate jdbc;
    private final StripeProperties stripe;

    private volatile double users;
    private volatile double activeSubscriptions;
    private volatile double customers;
    private volatile double mrrUsd;

    // priceId -> monthly-equivalent USD. Stripe prices are effectively immutable, so cache them
    // and never re-fetch — keeps MRR off the Stripe API on all but the first sighting of a price.
    private final Map<String, Double> monthlyUsdByPrice = new ConcurrentHashMap<>();

    public BusinessMetrics(MeterRegistry registry, JdbcTemplate jdbc, StripeProperties stripe) {
        this.jdbc = jdbc;
        this.stripe = stripe;

        Gauge.builder("diamond.users", this, m -> m.users)
            .description("Total registered users").register(registry);
        Gauge.builder("diamond.subscriptions.active", this, m -> m.activeSubscriptions)
            .description("Active or trialing subscriptions (Pro users)").register(registry);
        Gauge.builder("diamond.subscriptions.customers", this, m -> m.customers)
            .description("Users with a Stripe customer record").register(registry);
        Gauge.builder("diamond.mrr.usd", this, m -> m.mrrUsd)
            .description("Monthly recurring revenue in USD").register(registry);

        refresh(); // prime once so the gauges aren't zero until the first scheduled tick
    }

    @Scheduled(fixedRate = 60_000L)
    void refresh() {
        Long u = tryCount("SELECT count(*) FROM users");
        if (u != null) users = u;
        Long a = tryCount("SELECT count(*) FROM subscriptions WHERE status IN ('active', 'trialing')");
        if (a != null) activeSubscriptions = a;
        Long c = tryCount("SELECT count(*) FROM subscriptions WHERE stripe_customer_id IS NOT NULL");
        if (c != null) customers = c;
        Double m = tryMrr();
        if (m != null) mrrUsd = m;
    }

    private Long tryCount(String sql) {
        try {
            return jdbc.queryForObject(sql, Long.class);
        } catch (RuntimeException e) {
            log.debug("business metric query failed ({}), keeping last value", sql, e);
            return null;
        }
    }

    /** MRR = sum over active subscriptions of their price's monthly-equivalent amount. */
    private Double tryMrr() {
        if (!stripe.enabled()) return 0.0;
        try {
            double mrr = 0.0;
            List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT price_id, count(*) AS c FROM subscriptions "
                    + "WHERE status IN ('active', 'trialing') AND price_id IS NOT NULL GROUP BY price_id");
            for (Map<String, Object> row : rows) {
                Double monthly = monthlyUsd((String) row.get("price_id"));
                if (monthly != null) mrr += ((Number) row.get("c")).longValue() * monthly;
            }
            return mrr;
        } catch (RuntimeException e) {
            log.debug("MRR computation failed, keeping last value", e);
            return null;
        }
    }

    private Double monthlyUsd(String priceId) {
        Double cached = monthlyUsdByPrice.get(priceId);
        if (cached != null) return cached;
        try {
            Price price = Price.retrieve(priceId);
            Long unitAmount = price.getUnitAmount(); // cents
            if (unitAmount == null) return null;
            double usd = unitAmount / 100.0;
            String interval = price.getRecurring() != null ? price.getRecurring().getInterval() : "month";
            double monthly = switch (interval) {
                case "year" -> usd / 12.0;
                case "week" -> usd * 52.0 / 12.0;
                case "day" -> usd * 365.0 / 12.0;
                default -> usd; // month
            };
            monthlyUsdByPrice.put(priceId, monthly);
            return monthly;
        } catch (StripeException e) {
            log.warn("Could not fetch Stripe price {} for MRR", priceId, e);
            return null;
        }
    }
}
