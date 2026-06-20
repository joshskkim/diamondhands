package com.diamond.api.billing;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class StripePropertiesTest {

    private StripeProperties props(String secret) {
        return new StripeProperties(secret, "whsec", "price_m", "price_a", "http://localhost:3000");
    }

    @Test
    void disabledWhenSecretMissing() {
        assertFalse(props(null).enabled());
        assertFalse(props("").enabled());
        assertFalse(props("   ").enabled());
    }

    @Test
    void enabledWhenSecretPresent() {
        assertTrue(props("sk_test_123").enabled());
    }

    @Test
    void priceForResolvesInterval() {
        StripeProperties p = props("sk_test_123");
        assertEquals("price_a", p.priceFor("annual"));
        assertEquals("price_a", p.priceFor("ANNUAL"));
        assertEquals("price_m", p.priceFor("monthly"));
        assertEquals("price_m", p.priceFor("anything-else-defaults-to-monthly"));
    }
}
