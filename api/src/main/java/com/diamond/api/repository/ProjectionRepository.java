package com.diamond.api.repository;

import com.diamond.api.dto.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;

@Repository
public class ProjectionRepository {

    private static final String BATTER_PROJECTIONS_SQL = """
        SELECT
            bp.player_id,
            bp.is_home,
            bp.expected_pa,
            bp.p_hit_1plus, bp.p_hit_2plus, bp.p_hr, bp.p_k_1plus,
            bp.expected_hits, bp.expected_total_bases,
            bp.adj_park, bp.adj_pitcher, bp.adj_weather_hr, bp.adj_weather_hits, bp.adj_defense,
            bp.pitcher_data_quality,
            bp.lineup_position, bp.lineup_confirmed,
            bp.matchup_xwoba, bp.matchup_quality,
            g.game_date,
            p.full_name     AS batter_name,
            p.bats,
            p.position,
            pit.id          AS pitcher_id,
            pit.full_name   AS pitcher_name,
            pit.throws,
            ht.abbreviation AS home_abbr,
            at2.abbreviation AS away_abbr
        FROM batter_projections bp
        JOIN players p   ON p.id   = bp.player_id
        JOIN players pit ON pit.id = bp.opposing_pitcher_id
        JOIN games g     ON g.id   = bp.game_id
        JOIN teams ht    ON ht.id  = g.home_team_id
        JOIN teams at2   ON at2.id = g.away_team_id
        WHERE bp.game_id = ?
        ORDER BY bp.is_home DESC, bp.lineup_position ASC NULLS LAST, bp.expected_pa DESC
        """;

    private final JdbcTemplate jdbc;

    public ProjectionRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<BatterRow> findByGameId(long gameId) {
        return jdbc.query(BATTER_PROJECTIONS_SQL, this::mapRow, gameId);
    }

    // A starter's season skill split vs LHB / RHB (one row per handedness present).
    private static final String PITCHER_SKILL_SQL = """
        SELECT vs_handedness, k_rate, bb_rate, xwoba_against, hr_per_pa, batters_faced
        FROM pitcher_skill
        WHERE player_id = ? AND season = ?
        ORDER BY vs_handedness
        """;

    /** Season K%/BB%/xwOBA-against/HR-per-PA splits for one pitcher (empty when none). */
    public List<PitcherSkillSplitDto> pitcherSkillSplits(int pitcherId, int season) {
        return jdbc.query(
            PITCHER_SKILL_SQL,
            (rs, n) -> new PitcherSkillSplitDto(
                rs.getString("vs_handedness"),
                toDouble(rs.getBigDecimal("k_rate")),
                toDouble(rs.getBigDecimal("bb_rate")),
                toDouble(rs.getBigDecimal("xwoba_against")),
                toDouble(rs.getBigDecimal("hr_per_pa")),
                rs.getObject("batters_faced", Integer.class)),
            pitcherId, season);
    }

    private BatterRow mapRow(ResultSet rs, int rowNum) throws SQLException {
        PlayerDto player = new PlayerDto(
            rs.getInt("player_id"),
            rs.getString("batter_name"),
            rs.getString("bats"),
            rs.getString("position"));

        PitcherDto pitcher = new PitcherDto(
            rs.getInt("pitcher_id"),
            rs.getString("pitcher_name"),
            rs.getString("throws"));

        ProbabilitiesDto probs = new ProbabilitiesDto(
            toDouble(rs.getBigDecimal("p_hit_1plus")),
            toDouble(rs.getBigDecimal("p_hit_2plus")),
            toDouble(rs.getBigDecimal("p_hr")),
            toDouble(rs.getBigDecimal("p_k_1plus")));

        AdjustmentsDto adjs = new AdjustmentsDto(
            toDouble(rs.getBigDecimal("adj_park")),
            toDouble(rs.getBigDecimal("adj_pitcher")),
            toDouble(rs.getBigDecimal("adj_weather_hr")),
            toDouble(rs.getBigDecimal("adj_weather_hits")),
            toDouble(rs.getBigDecimal("adj_defense")));

        // Arsenal lists are filled in by ProjectionService (it needs game_date and
        // the pitch repo); mapped here as null so the row is otherwise complete.
        BatterProjectionDto proj = new BatterProjectionDto(
            player, pitcher,
            toDouble(rs.getBigDecimal("expected_pa")),
            probs,
            toDouble(rs.getBigDecimal("expected_hits")),
            toDouble(rs.getBigDecimal("expected_total_bases")),
            adjs,
            rs.getString("pitcher_data_quality"),
            rs.getObject("lineup_position", Integer.class),
            rs.getObject("lineup_confirmed", Boolean.class),
            toDouble(rs.getBigDecimal("matchup_xwoba")),
            rs.getString("matchup_quality"),
            null, null);

        return new BatterRow(
            rs.getBoolean("is_home"),
            rs.getString("home_abbr"),
            rs.getString("away_abbr"),
            rs.getObject("game_date", LocalDate.class),
            proj);
    }

    private static Double toDouble(BigDecimal bd) {
        return bd == null ? null : bd.doubleValue();
    }

    public record BatterRow(
        boolean isHome, String homeAbbr, String awayAbbr, LocalDate gameDate, BatterProjectionDto projection) {}
}
