package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;

/**
 * Reads the daily_accuracy snapshots written by the ingester's compute-accuracy command.
 * The service groups these by market into per-day trend series + the latest calibration curve.
 */
@Repository
public class AccuracyRepository {

    private final JdbcTemplate jdbc;

    public AccuracyRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // Pin the trend to a single model version (the most recent one scored) so the chart
    // doesn't mix versions across a model bump.
    private static final String LATEST_VERSION_SQL = """
        SELECT model_version FROM daily_accuracy
        ORDER BY slate_date DESC, computed_at DESC
        LIMIT 1
        """;

    private static final String ROWS_SQL = """
        SELECT slate_date, market, n, brier, baseline_brier, ece, calibration_buckets, mae
        FROM daily_accuracy
        WHERE model_version = ? AND slate_date >= ?
        ORDER BY market, slate_date
        """;

    /** The most recently scored model version, or null if no accuracy has been computed yet. */
    public String latestModelVersion() {
        return jdbc.query(LATEST_VERSION_SQL, rs -> rs.next() ? rs.getString(1) : null);
    }

    /** All snapshots for {@code modelVersion} on or after {@code since}, ordered by market then date. */
    public List<AccuracyRow> recentRows(String modelVersion, LocalDate since) {
        return jdbc.query(ROWS_SQL, this::map, modelVersion, since);
    }

    private AccuracyRow map(ResultSet rs, int rowNum) throws SQLException {
        return new AccuracyRow(
            rs.getObject("slate_date", LocalDate.class),
            rs.getString("market"),
            rs.getInt("n"),
            toDouble(rs.getBigDecimal("brier")),
            toDouble(rs.getBigDecimal("baseline_brier")),
            toDouble(rs.getBigDecimal("ece")),
            rs.getString("calibration_buckets"), // jsonb arrives as its JSON text
            toDouble(rs.getBigDecimal("mae")));
    }

    private static Double toDouble(BigDecimal bd) {
        return bd == null ? null : bd.doubleValue();
    }

    public record AccuracyRow(
        LocalDate slateDate, String market, int n,
        Double brier, Double baselineBrier, Double ece,
        String calibrationJson, Double mae) {}
}
