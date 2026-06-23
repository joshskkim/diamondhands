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
 * The service does the unit/ROI math.
 *
 * <p>The {@code lotto} column ships with the (separate) Lotto feature, so it may not exist yet on
 * every DB. We detect it at runtime and only select it when present — the query stays valid on a
 * fresh DB (Lotto picks simply fold into the Standard tier until the column lands), with no
 * migration coupling between the two features.
 */
@Repository
public class TrackRecordRepository {

    // Settled = scored_at set. won distinguishes win/loss; a graded row with won NULL is a push
    // (result_value present) or a void (result_value NULL, e.g. a postponed game) — the service
    // separates those. Ordered oldest-first so the equity curve accumulates in time order.
    // %s is the lotto projection: the real column when it exists, else a constant false.
    private static final String SETTLED_SQL = """
        SELECT slate_date, market, strong, won, model_prob, price_american, result_value,
               model_version, clv, %s AS lotto
        FROM model_picks
        WHERE scored_at IS NOT NULL AND slate_date >= ?
        ORDER BY slate_date, rank
        """;

    private final JdbcTemplate jdbc;
    private volatile Boolean lottoColumnExists;  // memoized one-shot detection

    public TrackRecordRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Settled picks on or after {@code since}, oldest first. */
    public List<SettledPick> settledSince(LocalDate since) {
        String sql = SETTLED_SQL.formatted(hasLottoColumn() ? "lotto" : "FALSE");
        return jdbc.query(sql, this::map, since);
    }

    private boolean hasLottoColumn() {
        Boolean cached = lottoColumnExists;
        if (cached == null) {
            cached = Boolean.TRUE.equals(jdbc.queryForObject(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'model_picks' AND column_name = 'lotto'
                )
                """,
                Boolean.class));
            lottoColumnExists = cached;
        }
        return cached;
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
            rs.getString("model_version"),
            toDouble(rs.getBigDecimal("clv")),
            rs.getBoolean("lotto"));
    }

    private static Double toDouble(BigDecimal bd) {
        return bd == null ? null : bd.doubleValue();
    }

    /** A graded pick. {@code won} null = push or void (disambiguated by {@code resultValue}).
     *  {@code clv} null when no closing quote was found at scoring time. */
    public record SettledPick(
        LocalDate slateDate,
        String market,
        boolean strong,
        Boolean won,
        double modelProb,
        int priceAmerican,
        Double resultValue,
        String modelVersion,
        Double clv,
        boolean lotto) {}
}
