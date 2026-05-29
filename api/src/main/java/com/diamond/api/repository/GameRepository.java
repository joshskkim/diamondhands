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
public class GameRepository {

    private static final String TODAY_GAMES_SQL = """
        SELECT
            g.id                            AS game_id,
            g.start_time_utc,
            g.status,
            g.projected_at,
            ht.id                           AS home_team_id,
            ht.abbreviation                 AS home_abbr,
            ht.name                         AS home_name,
            at2.id                          AS away_team_id,
            at2.abbreviation                AS away_abbr,
            at2.name                        AS away_name,
            s.name                          AS stadium_name,
            s.is_dome,
            g.temperature_f,
            g.wind_speed_mph,
            g.wind_direction_degrees,
            hp.id                           AS home_pitcher_id,
            hp.full_name                    AS home_pitcher_name,
            ap.id                           AS away_pitcher_id,
            ap.full_name                    AS away_pitcher_name,
            gp.expected_home_runs,
            gp.expected_away_runs,
            gp.expected_total_runs,
            gp.computed_at                  AS gp_computed_at
        FROM games g
        JOIN teams ht  ON ht.id  = g.home_team_id
        JOIN teams at2 ON at2.id = g.away_team_id
        JOIN stadiums s ON s.id  = g.stadium_id
        LEFT JOIN players hp ON hp.id = g.home_probable_pitcher_id
        LEFT JOIN players ap ON ap.id = g.away_probable_pitcher_id
        LEFT JOIN game_projections gp ON gp.game_id = g.id
        WHERE g.game_date = ?
        ORDER BY g.start_time_utc
        """;

    private final JdbcTemplate jdbc;

    public GameRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<TodayGameDto> findByDate(LocalDate date) {
        return jdbc.query(TODAY_GAMES_SQL, this::mapTodayGame, date);
    }

    private TodayGameDto mapTodayGame(ResultSet rs, int rowNum) throws SQLException {
        TeamDto home = new TeamDto(
            rs.getInt("home_team_id"),
            rs.getString("home_abbr"),
            rs.getString("home_name"));

        TeamDto away = new TeamDto(
            rs.getInt("away_team_id"),
            rs.getString("away_abbr"),
            rs.getString("away_name"));

        StadiumDto stadium = new StadiumDto(
            rs.getString("stadium_name"),
            rs.getBoolean("is_dome"));

        WeatherDto weather = new WeatherDto(
            nullableInt(rs, "temperature_f"),
            nullableInt(rs, "wind_speed_mph"),
            nullableInt(rs, "wind_direction_degrees"));

        Integer homePitcherId = nullableInt(rs, "home_pitcher_id");
        Integer awayPitcherId = nullableInt(rs, "away_pitcher_id");
        ProbablesDto probables = new ProbablesDto(
            homePitcherId != null ? new ProbableDto(homePitcherId, rs.getString("home_pitcher_name")) : null,
            awayPitcherId != null ? new ProbableDto(awayPitcherId, rs.getString("away_pitcher_name")) : null);

        BigDecimal homeRuns = rs.getBigDecimal("expected_home_runs");
        ProjectionSummaryDto projection = homeRuns != null
            ? new ProjectionSummaryDto(
                homeRuns.doubleValue(),
                rs.getBigDecimal("expected_away_runs").doubleValue(),
                rs.getBigDecimal("expected_total_runs").doubleValue(),
                rs.getString("gp_computed_at"))
            : null;

        return new TodayGameDto(
            rs.getLong("game_id"),
            rs.getString("start_time_utc"),
            home, away, stadium, weather, probables, projection,
            rs.getString("status"));
    }

    private static Integer nullableInt(ResultSet rs, String col) throws SQLException {
        int val = rs.getInt(col);
        return rs.wasNull() ? null : val;
    }
}
