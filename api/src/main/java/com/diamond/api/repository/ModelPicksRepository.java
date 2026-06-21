package com.diamond.api.repository;

import com.diamond.api.dto.ModelPickResultDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;

/**
 * Reads the persisted Model's Picks (model_picks) with their graded outcomes for a
 * slate. The board itself is computed client-side; this exposes the recorded snapshot
 * so the UI can show ✓/✗ once score-picks has graded it.
 */
@Repository
public class ModelPicksRepository {

    private static final String PICKS_SQL = """
        SELECT slate_date, rank, game_id, market, side, line, player_id, player_name,
               matchup, model_prob, fair_prob, edge, ev_pct, price_american, book,
               strong, result_value, won, scored_at
        FROM model_picks
        WHERE slate_date = ?
        ORDER BY rank
        """;

    private final JdbcTemplate jdbc;

    public ModelPicksRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<ModelPickResultDto> findByDate(LocalDate date) {
        return jdbc.query(PICKS_SQL, this::map, date);
    }

    private ModelPickResultDto map(ResultSet rs, int rowNum) throws SQLException {
        return new ModelPickResultDto(
            rs.getString("slate_date"),
            rs.getInt("rank"),
            rs.getLong("game_id"),
            rs.getString("market"),
            rs.getString("side"),
            dbl(rs, "line"),
            nullableInt(rs, "player_id"),
            rs.getString("player_name"),
            rs.getString("matchup"),
            dbl(rs, "model_prob"),
            dbl(rs, "fair_prob"),
            dbl(rs, "edge"),
            dbl(rs, "ev_pct"),
            nullableInt(rs, "price_american"),
            rs.getString("book"),
            rs.getBoolean("strong"),
            dbl(rs, "result_value"),
            (Boolean) rs.getObject("won"),
            rs.getObject("scored_at") != null);
    }

    private static Double dbl(ResultSet rs, String col) throws SQLException {
        BigDecimal v = rs.getBigDecimal(col);
        return v == null ? null : v.doubleValue();
    }

    private static Integer nullableInt(ResultSet rs, String col) throws SQLException {
        int val = rs.getInt(col);
        return rs.wasNull() ? null : val;
    }
}
