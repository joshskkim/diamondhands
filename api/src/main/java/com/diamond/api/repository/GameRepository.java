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

    /** Single book shown for game markets on the today board (best US coverage of ML/total). */
    public static final String MAIN_GAME_BOOK = "fanduel";

    private static final String TODAY_GAMES_SQL = """
        SELECT
            g.id                            AS game_id,
            g.start_time_utc,
            g.status,
            g.detailed_status,
            g.projected_at,
            g.home_score,
            g.away_score,
            g.home_score_1st,
            g.away_score_1st,
            g.live_home_score,
            g.live_away_score,
            g.live_current_inning,
            g.live_inning_state,
            g.live_is_top,
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
            gp.computed_at                  AS gp_computed_at,
            fdo.fd_total_line,
            fdo.fd_total_over,
            fdo.fd_total_under,
            fdo.fd_ml_home,
            fdo.fd_ml_away
        FROM games g
        JOIN teams ht  ON ht.id  = g.home_team_id
        JOIN teams at2 ON at2.id = g.away_team_id
        JOIN stadiums s ON s.id  = g.stadium_id
        LEFT JOIN players hp ON hp.id = g.home_probable_pitcher_id
        LEFT JOIN players ap ON ap.id = g.away_probable_pitcher_id
        LEFT JOIN game_projections gp ON gp.game_id = g.id
        LEFT JOIN (
            SELECT game_id,
                MAX(line)           FILTER (WHERE market='total'     AND side='over')  AS fd_total_line,
                MAX(price_american) FILTER (WHERE market='total'     AND side='over')  AS fd_total_over,
                MAX(price_american) FILTER (WHERE market='total'     AND side='under') AS fd_total_under,
                MAX(price_american) FILTER (WHERE market='moneyline' AND side='home')  AS fd_ml_home,
                MAX(price_american) FILTER (WHERE market='moneyline' AND side='away')  AS fd_ml_away
            FROM game_odds
            WHERE bookmaker = 'fanduel'
            GROUP BY game_id
        ) fdo ON fdo.game_id = g.id
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

        GameOddsSummaryDto odds = mapOdds(rs);

        return new TodayGameDto(
            rs.getLong("game_id"),
            rs.getString("start_time_utc"),
            home, away, stadium, weather, probables, projection, odds,
            rs.getString("status"),
            rs.getString("detailed_status"),
            nullableInt(rs, "home_score"),
            nullableInt(rs, "away_score"),
            nullableInt(rs, "home_score_1st"),
            nullableInt(rs, "away_score_1st"),
            nullableInt(rs, "live_home_score"),
            nullableInt(rs, "live_away_score"),
            nullableInt(rs, "live_current_inning"),
            rs.getString("live_inning_state"),
            nullableBool(rs, "live_is_top"));
    }

    private static final String LIVE_GAMES_SQL = """
        SELECT
            g.id                  AS game_id,
            g.status,
            g.live_home_score,
            g.live_away_score,
            g.live_current_inning,
            g.live_inning_state,
            g.live_is_top
        FROM games g
        WHERE g.game_date = ?
        ORDER BY g.start_time_utc
        """;

    /** Lean live-state read for the SSE broadcaster — no joins, no cache. */
    public List<LiveGameDto> findLiveByDate(LocalDate date) {
        return jdbc.query(LIVE_GAMES_SQL, GameRepository::mapLiveGame, date);
    }

    private static LiveGameDto mapLiveGame(ResultSet rs, int rowNum) throws SQLException {
        return new LiveGameDto(
            rs.getLong("game_id"),
            rs.getString("status"),
            nullableInt(rs, "live_home_score"),
            nullableInt(rs, "live_away_score"),
            nullableInt(rs, "live_current_inning"),
            rs.getString("live_inning_state"),
            nullableBool(rs, "live_is_top"));
    }

    /** FanDuel game-market summary, or null when the game has no FanDuel odds. */
    private GameOddsSummaryDto mapOdds(ResultSet rs) throws SQLException {
        BigDecimal totalLine = rs.getBigDecimal("fd_total_line");
        Integer over = nullableInt(rs, "fd_total_over");
        Integer under = nullableInt(rs, "fd_total_under");
        Integer mlHome = nullableInt(rs, "fd_ml_home");
        Integer mlAway = nullableInt(rs, "fd_ml_away");
        if (totalLine == null && over == null && under == null && mlHome == null && mlAway == null) {
            return null;
        }
        return new GameOddsSummaryDto(
            MAIN_GAME_BOOK,
            totalLine != null ? totalLine.doubleValue() : null,
            over, under, mlHome, mlAway);
    }

    private static Integer nullableInt(ResultSet rs, String col) throws SQLException {
        int val = rs.getInt(col);
        return rs.wasNull() ? null : val;
    }

    private static Boolean nullableBool(ResultSet rs, String col) throws SQLException {
        boolean val = rs.getBoolean(col);
        return rs.wasNull() ? null : val;
    }
}
