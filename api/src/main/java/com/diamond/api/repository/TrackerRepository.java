package com.diamond.api.repository;

import com.diamond.api.dto.TrackerResponse.TrackerEntry;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;

/** Reads a user's Tracker rows: tailed Analyst recommendations + logged bets, graded. */
@Repository
public class TrackerRepository {

    private final JdbcTemplate jdbc;

    public TrackerRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final String RECS_SQL = """
        SELECT id, slate_date, game_id, market, side, line, player_id, player_name,
               price_american, book, stake_units, confidence, model_prob, fair_prob, edge,
               result_value, won, clv, (scored_at IS NOT NULL) AS scored
        FROM agent_recommendations
        WHERE user_id = ?
        ORDER BY slate_date DESC, recorded_at DESC
        """;

    private static final String BETS_SQL = """
        SELECT id, slate_date, game_id, market, side, line, player_id, player_name,
               price_american, book, stake_units, result_value, won, clv, status,
               (scored_at IS NOT NULL) AS scored
        FROM user_bets
        WHERE user_id = ?
        ORDER BY slate_date DESC, placed_at DESC
        """;

    public List<TrackerEntry> findRecommendations(long userId) {
        return jdbc.query(RECS_SQL, (rs, n) -> new TrackerEntry(
            rs.getLong("id"), "agent", rs.getString("slate_date"), rs.getLong("game_id"),
            rs.getString("market"), rs.getString("side"), dbl(rs, "line"),
            nullableInt(rs, "player_id"), rs.getString("player_name"),
            nullableInt(rs, "price_american"), rs.getString("book"),
            dbl(rs, "stake_units"), dbl(rs, "confidence"), dbl(rs, "model_prob"),
            dbl(rs, "fair_prob"), dbl(rs, "edge"), (Boolean) rs.getObject("won"),
            dbl(rs, "result_value"), dbl(rs, "clv"), rs.getBoolean("scored"), "tracked"),
            userId);
    }

    public List<TrackerEntry> findBets(long userId) {
        return jdbc.query(BETS_SQL, (rs, n) -> new TrackerEntry(
            rs.getLong("id"), "personal", rs.getString("slate_date"), rs.getLong("game_id"),
            rs.getString("market"), rs.getString("side"), dbl(rs, "line"),
            nullableInt(rs, "player_id"), rs.getString("player_name"),
            nullableInt(rs, "price_american"), rs.getString("book"),
            dbl(rs, "stake_units"), null, null, null, null,
            (Boolean) rs.getObject("won"), dbl(rs, "result_value"), dbl(rs, "clv"),
            rs.getBoolean("scored"), rs.getString("status")),
            userId);
    }

    /** True if the user already tailed this selection on this slate (idempotent Tail). */
    public boolean recommendationExists(long userId, LocalDate slate, long gameId, String market,
                                        String side, Integer playerId) {
        Integer c = jdbc.queryForObject(
            "SELECT count(*) FROM agent_recommendations WHERE user_id=? AND slate_date=? "
            + "AND game_id=? AND market=? AND side=? AND player_id IS NOT DISTINCT FROM ?",
            Integer.class, userId, slate, gameId, market, side, playerId);
        return c != null && c > 0;
    }

    private static Double dbl(ResultSet rs, String col) throws SQLException {
        BigDecimal v = rs.getBigDecimal(col);
        return v == null ? null : v.doubleValue();
    }

    private static Integer nullableInt(ResultSet rs, String col) throws SQLException {
        int v = rs.getInt(col);
        return rs.wasNull() ? null : v;
    }
}
