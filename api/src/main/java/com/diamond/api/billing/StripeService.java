package com.diamond.api.billing;

import com.diamond.api.auth.AuthUser;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.stripe.exception.StripeException;
import com.stripe.model.Customer;
import com.stripe.model.Event;
import com.stripe.model.StripeObject;
import com.stripe.model.Subscription;
import com.stripe.model.checkout.Session;
import com.stripe.net.Webhook;
import com.stripe.param.CustomerCreateParams;
import com.stripe.param.checkout.SessionCreateParams;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Optional;

/**
 * Stripe Checkout + Customer Portal + webhook handling. The Stripe customer is created
 * lazily on first checkout and linked to the user; webhooks then keep the local
 * {@code subscriptions} row in sync (located by customer id). The app reads entitlement
 * from our DB, never from Stripe at request time. See docs/auth-design.md "Payments".
 */
@Service
public class StripeService {

    private static final Logger log = LoggerFactory.getLogger(StripeService.class);

    private final StripeProperties props;
    private final SubscriptionRepository subs;

    public StripeService(StripeProperties props, SubscriptionRepository subs) {
        this.props = props;
        this.subs = subs;
    }

    /** Create a Checkout Session for the user + interval, returning the redirect URL. */
    public String createCheckoutUrl(AuthUser user, String interval) throws StripeException {
        String priceId = props.priceFor(interval);
        if (priceId == null || priceId.isBlank()) {
            throw new IllegalStateException("No Stripe price configured for interval: " + interval);
        }
        String customerId = ensureCustomer(user);
        Session session = Session.create(SessionCreateParams.builder()
            .setMode(SessionCreateParams.Mode.SUBSCRIPTION)
            .setCustomer(customerId)
            .setClientReferenceId(String.valueOf(user.id()))
            .setSuccessUrl(props.webBaseUrl() + "/billing/success")
            .setCancelUrl(props.webBaseUrl() + "/billing/cancel")
            .addLineItem(SessionCreateParams.LineItem.builder()
                .setPrice(priceId)
                .setQuantity(1L)
                .build())
            .build());
        return session.getUrl();
    }

    /** Create a Customer Portal session (manage/cancel). Empty if the user has no customer yet. */
    public Optional<String> createPortalUrl(AuthUser user) throws StripeException {
        Optional<String> customerId = subs.findCustomerId(user.id());
        if (customerId.isEmpty()) return Optional.empty();
        com.stripe.model.billingportal.Session session =
            com.stripe.model.billingportal.Session.create(
                com.stripe.param.billingportal.SessionCreateParams.builder()
                    .setCustomer(customerId.get())
                    .setReturnUrl(props.webBaseUrl() + "/profile")
                    .build());
        return Optional.of(session.getUrl());
    }

    private String ensureCustomer(AuthUser user) throws StripeException {
        Optional<String> existing = subs.findCustomerId(user.id());
        if (existing.isPresent()) return existing.get();
        Customer customer = Customer.create(CustomerCreateParams.builder()
            .setEmail(user.email())
            .putMetadata("user_id", String.valueOf(user.id()))
            .putMetadata("handle", user.handle())
            .build());
        subs.linkCustomer(user.id(), customer.getId());
        return customer.getId();
    }

    /**
     * Verify the Stripe signature and apply the event. Idempotent: each handler writes the
     * subscription's absolute current state, so a replayed webhook is a harmless no-op.
     */
    public void handleWebhook(String payload, String signatureHeader) throws StripeException {
        Event event = Webhook.constructEvent(payload, signatureHeader, props.webhookSecret());
        switch (event.getType()) {
            case "checkout.session.completed" -> onCheckoutCompleted(event);
            case "customer.subscription.updated", "customer.subscription.deleted",
                 "customer.subscription.created" -> deserialize(event, Subscription.class)
                    .ifPresent(this::syncFromSubscription);
            default -> { /* ignore everything else */ }
        }
    }

    private void onCheckoutCompleted(Event event) throws StripeException {
        Optional<Session> session = deserialize(event, Session.class);
        if (session.isEmpty()) return;
        String subId = session.get().getSubscription();
        if (subId == null) return; // not a subscription checkout
        syncFromSubscription(Subscription.retrieve(subId));
    }

    private void syncFromSubscription(Subscription sub) {
        String priceId = sub.getItems() == null || sub.getItems().getData().isEmpty()
            ? null
            : sub.getItems().getData().get(0).getPrice().getId();
        subs.syncByCustomer(
            sub.getCustomer(),
            sub.getId(),
            sub.getStatus(),
            priceId,
            currentPeriodEnd(sub),
            Boolean.TRUE.equals(sub.getCancelAtPeriodEnd()));
    }

    /**
     * {@code current_period_end} lives on the subscription (older API versions) or on the
     * subscription item (Basil 2025-03+). Read it from the raw JSON so we work across both
     * without a hard getter dependency; it's informational, so any failure yields null.
     */
    private static Instant currentPeriodEnd(Subscription sub) {
        try {
            JsonObject root = sub.getRawJsonObject();
            Long epoch = asLong(root.get("current_period_end"));
            if (epoch == null && root.has("items")) {
                JsonArray data = root.getAsJsonObject("items").getAsJsonArray("data");
                if (data != null && data.size() > 0) {
                    epoch = asLong(data.get(0).getAsJsonObject().get("current_period_end"));
                }
            }
            return epoch == null ? null : Instant.ofEpochSecond(epoch);
        } catch (RuntimeException e) {
            log.debug("Could not read current_period_end for {}", sub.getId(), e);
            return null;
        }
    }

    private static Long asLong(JsonElement el) {
        return el == null || el.isJsonNull() ? null : el.getAsLong();
    }

    private static <T extends StripeObject> Optional<T> deserialize(Event event, Class<T> type) {
        return event.getDataObjectDeserializer().getObject()
            .filter(type::isInstance)
            .map(type::cast);
    }
}
