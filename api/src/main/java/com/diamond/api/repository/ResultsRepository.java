package com.diamond.api.repository;

import com.diamond.api.dto.BatterResultDto;
import com.diamond.api.dto.PitcherResultDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;

/**
 * Reads actual per-player game lines for a slate: batting from player_game_stats and
 * starter workload from pitcher_starts. Both are keyed by (player_id, game_id) on the
 * client so a forward-looking pick can be matched to its outcome.
 */
@Repository
public class ResultsRepository {

    private static final String BATTERS_SQL = """
        SELECT player_id, game_id, hits, home_runs, strikeouts, walks
        FROM player_game_stats
        WHERE game_date = ? AND game_id IS NOT NULL
        """;

    private static final String PITCHERS_SQL = """
        SELECT player_id, game_id, strikeouts, outs, hits_allowed, earned_runs
        FROM pitcher_starts
        WHERE game_date = ?
        """;

    private final JdbcTemplate jdbc;

    public ResultsRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<BatterResultDto> findBatters(LocalDate date) {
        return jdbc.query(BATTERS_SQL, this::mapBatter, date);
    }

    public List<PitcherResultDto> findPitchers(LocalDate date) {
        return jdbc.query(PITCHERS_SQL, this::mapPitcher, date);
    }

    private BatterResultDto mapBatter(ResultSet rs, int n) throws SQLException {
        return new BatterResultDto(
            rs.getInt("player_id"),
            rs.getLong("game_id"),
            nullableInt(rs, "hits"),
            nullableInt(rs, "home_runs"),
            nullableInt(rs, "strikeouts"),
            nullableInt(rs, "walks"));
    }

    private PitcherResultDto mapPitcher(ResultSet rs, int n) throws SQLException {
        return new PitcherResultDto(
            rs.getInt("player_id"),
            rs.getLong("game_id"),
            nullableInt(rs, "strikeouts"),
            nullableInt(rs, "outs"),
            nullableInt(rs, "hits_allowed"),
            nullableInt(rs, "earned_runs"));
    }

    private static Integer nullableInt(ResultSet rs, String col) throws SQLException {
        int val = rs.getInt(col);
        return rs.wasNull() ? null : val;
    }
}
