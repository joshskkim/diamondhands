package com.diamond.api.repository;

import com.diamond.api.dto.ModelPickResultDto;
import com.diamond.api.dto.ReconcileRequest.PickKey;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

/**
 * Reads the persisted Model's Picks (model_picks) with their graded outcomes for a
 * slate. The board itself is computed client-side; this exposes the recorded snapshot
 * so the UI can show ✓/✗ once score-picks has graded it.
 */
@Repository
public class ModelPicksRepository {

    // Active picks first (board order), then earlier/bumped ones oldest-shown first.
    private static final String PICKS_SQL = """
        SELECT slate_date, rank, game_id, market, side, line, player_id, player_name,
               matchup, model_prob, fair_prob, edge, ev_pct, price_american, book,
               strong, result_value, won, scored_at, active,
               to_char(first_shown_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS first_shown_at,
               to_char(bumped_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS bumped_at
        FROM model_picks
        WHERE slate_date = ?
        ORDER BY active DESC, rank ASC NULLS LAST, first_shown_at ASC
        """;

    private final JdbcTemplate jdbc;

    public ModelPicksRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<ModelPickResultDto> findByDate(LocalDate date) {
        return jdbc.query(PICKS_SQL, this::map, date);
    }

    // ── reconcile (keep the recorded snapshot in step with the live board) ───────────
    // The minimum a live-board reconcile needs to decide bump/re-promote per recorded row.
    public record ReconcileRow(long id, long gameId, String market, String side, Integer playerId,
                               boolean active, boolean bumped, Instant startTime) {
        public PickKey key() {
            return new PickKey(gameId, market, side, playerId);
        }
    }

    private static final String RECONCILE_ROWS_SQL = """
        SELECT mp.id, mp.game_id, mp.market, mp.side, mp.player_id, mp.active,
               (mp.bumped_at IS NOT NULL) AS bumped, g.start_time_utc
        FROM model_picks mp JOIN games g ON g.id = mp.game_id
        WHERE mp.slate_date = ?
        """;

    public List<ReconcileRow> findReconcileRows(LocalDate date) {
        return jdbc.query(RECONCILE_ROWS_SQL, (rs, n) -> {
            Timestamp start = rs.getTimestamp("start_time_utc");
            return new ReconcileRow(
                rs.getLong("id"), rs.getLong("game_id"), rs.getString("market"),
                rs.getString("side"), nullableInt(rs, "player_id"), rs.getBoolean("active"),
                rs.getBoolean("bumped"), start == null ? null : start.toInstant());
        }, date);
    }

    /** Displaced before its game: mark inactive + stamp when, so it falls to "Earlier today". */
    public void bump(long id, Instant now) {
        jdbc.update("UPDATE model_picks SET active=false, bumped_at=? WHERE id=?",
            Timestamp.from(now), id);
    }

    /** Back in the live top set: re-promote and clear the bump (mirrors the cron's "keep"). */
    public void promote(long id, int rank) {
        jdbc.update("UPDATE model_picks SET active=true, bumped_at=NULL, rank=? WHERE id=?",
            rank, id);
    }

    private ModelPickResultDto map(ResultSet rs, int rowNum) throws SQLException {
        return new ModelPickResultDto(
            rs.getString("slate_date"),
            nullableInt(rs, "rank"),
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
            rs.getObject("scored_at") != null,
            rs.getBoolean("active"),
            rs.getString("first_shown_at"),
            rs.getString("bumped_at"));
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
