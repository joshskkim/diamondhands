package com.diamond.api.billing;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Stripe/billing config (see application.yml {@code app.stripe.*}). Billing is disabled
 * unless {@code secretKey} is set, so the endpoints degrade to 503 rather than erroring
 * when no key is configured (mirrors the AI feature's enable-on-key-present pattern).
 */
@ConfigurationProperties(prefix = "app.stripe")
public record StripeProperties(
    String secretKey,
    String webhookSecret,
    String priceMonthly,
    String priceAnnual,
    String webBaseUrl
) {
    public boolean enabled() {
        return secretKey != null && !secretKey.isBlank();
    }

    /** Resolve a price id from the requested interval ("monthly" / "annual"). */
    public String priceFor(String interval) {
        return "annual".equalsIgnoreCase(interval) ? priceAnnual : priceMonthly;
    }
}
