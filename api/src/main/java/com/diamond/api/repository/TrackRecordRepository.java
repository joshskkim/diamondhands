package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;

/**
 * Reads settled Model's Picks (model_picks rows that score-picks has graded) for the track record.
 * Only V30 columns are referenced so this works on a fresh DB; the service does the unit/ROI math.
 */
@Repository
public class TrackRecordRepository {

    // Settled = scored_at set. won distinguishes win/loss; a graded row with won NULL is a push
    // (result_value present) or a void (result_value NULL, e.g. a postponed game) — the service
    // separates those. Ordered oldest-first so the equity curve accumulates in time order.
    private static final String SETTLED_SQL = """
        SELECT slate_date, market, strong, won, model_prob, price_american, result_value,
               model_version
        FROM model_picks
        WHERE scored_at IS NOT NULL AND slate_date >= ?
        ORDER BY slate_date, rank
        """;

    private final JdbcTemplate jdbc;

    public TrackRecordRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Settled picks on or after {@code since}, oldest first. */
    public List<SettledPick> settledSince(LocalDate since) {
        return jdbc.query(SETTLED_SQL, this::map, since);
    }

    private SettledPick map(ResultSet rs, int rowNum) throws SQLException {
        return new SettledPick(
            rs.getObject("slate_date", LocalDate.class),
            rs.getString("market"),
            rs.getBoolean("strong"),
            (Boolean) rs.getObject("won"),
            rs.getBigDecimal("model_prob").doubleValue(),
            rs.getInt("price_american"),
            toDouble(rs.getBigDecimal("result_value")),
            rs.getString("model_version"));
    }

    private static Double toDouble(BigDecimal bd) {
        return bd == null ? null : bd.doubleValue();
    }

    /** A graded pick. {@code won} null = push or void (disambiguated by {@code resultValue}). */
    public record SettledPick(
        LocalDate slateDate,
        String market,
        boolean strong,
        Boolean won,
        double modelProb,
        int priceAmerican,
        Double resultValue,
        String modelVersion) {}
}
