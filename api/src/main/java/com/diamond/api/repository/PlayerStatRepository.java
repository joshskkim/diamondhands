package com.diamond.api.repository;

import com.diamond.api.dto.PlayerDetailDto;
import com.diamond.api.dto.RecentStatDto;
import com.diamond.api.dto.SprayResponse;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Optional;

@Repository
public class PlayerStatRepository {

    private static final String FIND_BY_ID_SQL = """
        SELECT p.id, p.full_name, p.team_id, t.abbreviation AS team_abbr,
               p.position, p.bats, p.throws
        FROM players p
        LEFT JOIN teams t ON t.id = p.team_id
        WHERE p.id = ?
        """;

    private static final String RECENT_STATS_SQL = """
        SELECT
            pgs.game_date,
            pgs.is_home,
            pgs.plate_appearances,
            pgs.hits,
            pgs.home_runs,
            pgs.strikeouts,
            pgs.xwoba,
            t.abbreviation AS opp
        FROM player_game_stats pgs
        LEFT JOIN teams t ON t.id = pgs.opponent_team_id
        WHERE pgs.player_id = ?
          AND pgs.plate_appearances IS NOT NULL
          AND pgs.plate_appearances > 0
          AND pgs.hits IS NOT NULL
        ORDER BY pgs.game_date DESC
        LIMIT ?
        """;

    // Spray bins are per-season; the season filter is mandatory (multi-season table).
    private static final String SPRAY_SQL = """
        SELECT bin, bip, hr, avg_distance_ft
        FROM batter_spray_bins
        WHERE player_id = ? AND season = ?
        ORDER BY bin
        """;

    private final JdbcTemplate jdbc;

    public PlayerStatRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<PlayerDetailDto> findById(int playerId) {
        List<PlayerDetailDto> rows = jdbc.query(FIND_BY_ID_SQL, (rs, n) -> new PlayerDetailDto(
            rs.getInt("id"),
            rs.getString("full_name"),
            nullableInt(rs, "team_id"),
            rs.getString("team_abbr"),
            rs.getString("position"),
            rs.getString("bats"),
            rs.getString("throws")),
            playerId);
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.get(0));
    }

    public List<RecentStatDto> findRecent(int playerId, int limit) {
        return jdbc.query(RECENT_STATS_SQL, this::mapRow, playerId, limit);
    }

    public List<SprayResponse.SprayBinDto> findSprayBins(int playerId, int season) {
        return jdbc.query(SPRAY_SQL, (rs, n) -> new SprayResponse.SprayBinDto(
            rs.getInt("bin"),
            rs.getInt("bip"),
            rs.getInt("hr"),
            rs.getObject("avg_distance_ft") == null
                ? null
                : rs.getBigDecimal("avg_distance_ft").doubleValue()),
            playerId, season);
    }

    private static Integer nullableInt(ResultSet rs, String col) throws SQLException {
        int val = rs.getInt(col);
        return rs.wasNull() ? null : val;
    }

    private RecentStatDto mapRow(ResultSet rs, int rowNum) throws SQLException {
        BigDecimal xwoba = rs.getBigDecimal("xwoba");
        return new RecentStatDto(
            rs.getString("game_date"),
            rs.getString("opp"),
            rs.getBoolean("is_home"),
            rs.getInt("plate_appearances"),
            rs.getInt("hits"),
            rs.getInt("home_runs"),
            rs.getInt("strikeouts"),
            xwoba == null ? null : xwoba.doubleValue());
    }
}
