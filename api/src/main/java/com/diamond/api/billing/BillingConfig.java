package com.diamond.api.billing;

import com.stripe.Stripe;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * Enables {@link StripeProperties} and sets the global Stripe API key once at startup.
 * No-op when billing is disabled (no secret key) — the controllers guard on that.
 */
@Configuration
@EnableConfigurationProperties(StripeProperties.class)
public class BillingConfig {

    private final StripeProperties props;

    public BillingConfig(StripeProperties props) {
        this.props = props;
    }

    @PostConstruct
    void initStripe() {
        if (props.enabled()) {
            Stripe.apiKey = props.secretKey();
        }
    }
}
