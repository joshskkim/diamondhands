package com.diamond.api.billing;

import com.stripe.exception.SignatureVerificationException;
import com.stripe.exception.StripeException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.diamond.api.auth.AuthUser;

/**
 * Stripe billing: start a Checkout subscription, open the Customer Portal, and receive
 * webhooks. Checkout/portal require a signed-in user (cookie session); the webhook is
 * public but authenticated by its Stripe signature instead. Disabled (503) when no Stripe
 * key is configured. Gates no features yet — this is billing plumbing + the Pro flag.
 */
@RestController
@RequestMapping("/api/billing")
public class BillingController {

    private static final Logger log = LoggerFactory.getLogger(BillingController.class);

    private final StripeService stripe;
    private final StripeProperties props;

    public BillingController(StripeService stripe, StripeProperties props) {
        this.stripe = stripe;
        this.props = props;
    }

    public record CheckoutRequest(String interval) {}

    public record UrlResponse(String url) {}

    @PostMapping("/checkout")
    public UrlResponse checkout(@AuthenticationPrincipal AuthUser user,
                                @RequestBody(required = false) CheckoutRequest req) {
        requireUser(user);
        requireEnabled();
        String interval = req == null || req.interval() == null ? "monthly" : req.interval();
        try {
            return new UrlResponse(stripe.createCheckoutUrl(user, interval));
        } catch (StripeException e) {
            throw upstream(e);
        }
    }

    @PostMapping("/portal")
    public UrlResponse portal(@AuthenticationPrincipal AuthUser user) {
        requireUser(user);
        requireEnabled();
        try {
            return stripe.createPortalUrl(user)
                .map(UrlResponse::new)
                .orElseThrow(() -> new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "No billing account yet — subscribe first"));
        } catch (StripeException e) {
            throw upstream(e);
        }
    }

    @PostMapping("/webhook")
    public ResponseEntity<Void> webhook(@RequestBody String payload,
                                        @RequestHeader("Stripe-Signature") String signature) {
        if (!props.enabled()) return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).build();
        try {
            stripe.handleWebhook(payload, signature);
            return ResponseEntity.ok().build();
        } catch (SignatureVerificationException e) {
            log.warn("Stripe webhook signature verification failed");
            return ResponseEntity.badRequest().build();
        } catch (StripeException | RuntimeException e) {
            // 5xx so Stripe retries a transient processing failure.
            log.error("Stripe webhook processing failed", e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).build();
        }
    }

    private void requireUser(AuthUser user) {
        if (user == null) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
    }

    private void requireEnabled() {
        if (!props.enabled()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Billing is not configured");
        }
    }

    private ResponseStatusException upstream(StripeException e) {
        log.error("Stripe API call failed", e);
        return new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Billing provider error");
    }
}
