package com.diamond.api.repository;

import com.diamond.api.ai.UserPreferences;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/** Reads/writes {@code user_preferences} — the agent's per-user long-term memory. */
@Repository
public class UserPreferenceRepository {

    private final JdbcTemplate jdbc;

    public UserPreferenceRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<UserPreferences> find(long userId) {
        List<UserPreferences> rows = jdbc.query(
            """
            SELECT user_id, bankroll_units, unit_size_usd, kelly_fraction, risk_profile,
                   briefing_channel, discord_webhook_url
            FROM user_preferences WHERE user_id = ?
            """,
            (rs, n) -> new UserPreferences(
                rs.getLong("user_id"),
                (Double) rs.getObject("bankroll_units"),
                (Double) rs.getObject("unit_size_usd"),
                rs.getDouble("kelly_fraction"),
                rs.getString("risk_profile"),
                rs.getString("briefing_channel"),
                rs.getString("discord_webhook_url")),
            userId);
        return rows.stream().findFirst();
    }

    public UserPreferences findOrDefault(long userId) {
        return find(userId).orElse(UserPreferences.defaults(userId));
    }

    /** Upsert bankroll/risk settings (the agent's set_bankroll / set_risk write actions). */
    public void upsert(UserPreferences p) {
        jdbc.update(
            """
            INSERT INTO user_preferences
                (user_id, bankroll_units, unit_size_usd, kelly_fraction, risk_profile,
                 briefing_channel, discord_webhook_url, updated_at)
            VALUES (?,?,?,?,?,?,?, now())
            ON CONFLICT (user_id) DO UPDATE SET
                bankroll_units = EXCLUDED.bankroll_units,
                unit_size_usd  = EXCLUDED.unit_size_usd,
                kelly_fraction = EXCLUDED.kelly_fraction,
                risk_profile   = EXCLUDED.risk_profile,
                briefing_channel = EXCLUDED.briefing_channel,
                discord_webhook_url = EXCLUDED.discord_webhook_url,
                updated_at = now()
            """,
            p.userId(), p.bankrollUnits(), p.unitSizeUsd(), p.kellyFraction(),
            p.riskProfile(), p.briefingChannel(), p.discordWebhookUrl());
    }
}
