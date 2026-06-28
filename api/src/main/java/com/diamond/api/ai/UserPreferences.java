package com.diamond.api.ai;

/**
 * The agent's long-term memory for one user: bankroll + risk settings that drive Kelly sizing
 * and the briefing target. {@code bankrollUnits == null} means sizing is disabled until the
 * user sets it (the agent must ask rather than guess).
 */
public record UserPreferences(
    long userId,
    Double bankrollUnits,
    Double unitSizeUsd,
    double kellyFraction,
    String riskProfile,
    String briefingChannel,
    String discordWebhookUrl) {

    /** Sensible defaults for a user with no preferences row yet. */
    public static UserPreferences defaults(long userId) {
        return new UserPreferences(userId, null, null, 0.25, "balanced", null, null);
    }

    public boolean canSize() {
        return bankrollUnits != null && bankrollUnits > 0;
    }
}
