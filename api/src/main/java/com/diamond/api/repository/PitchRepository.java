package com.diamond.api.repository;

import com.diamond.api.dto.PitchArsenalDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;

/**
 * Pitch-mix matchup queries (v2.1). All read from the point-in-time snapshot
 * tables, selecting the most recent as_of_date on/before the reference game date.
 * Empirical-Bayes regression of thin per-pitch-type samples is applied in Java
 * (see {@link #regress}) to mirror the projection engine's query-time regression.
 */
@Repository
public class PitchRepository {

    /** Phantom league-average pitches added to each batter sample (matches REGRESSION_K_PITCHES_BATTER). */
    public static final int REGRESSION_K_PITCHES_BATTER = 100;

    /** Empirical-Bayes blend of a raw rate toward its league mean by sample size. */
    public static Double regress(Double raw, int n, Double league, int k) {
        if (league == null) return raw;
        if (raw == null) return league;
        double w = (double) n / (n + k);
        return w * raw + (1.0 - w) * league;
    }

    private final JdbcTemplate jdbc;

    public PitchRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // ── arsenal of one pitcher vs a batter hand, with league xwOBA per pitch ──
    // The snapshot tables hold rows for multiple seasons under the same as_of_date,
    // so we pin the single latest (season, as_of_date) pair — not just MAX(as_of_date).
    private static final String ARSENAL_SQL = """
        SELECT a.pitch_type, a.usage_rate, a.xwoba_against, a.whiff_rate, a.avg_velocity, b.league_xwoba
        FROM pitcher_arsenal a
        LEFT JOIN pitch_type_league_baselines b
          ON b.season = a.season AND b.pitch_type = a.pitch_type AND b.vs_handedness = ?
        WHERE a.player_id = ? AND a.vs_handedness = ?
          AND (a.season, a.as_of_date) = (
              SELECT season, as_of_date FROM pitcher_arsenal
              WHERE player_id = ? AND vs_handedness = ? AND as_of_date <= ?
              ORDER BY as_of_date DESC, season DESC LIMIT 1
          )
        ORDER BY a.usage_rate DESC
        """;

    public List<PitchArsenalDto> arsenal(int pitcherId, String pitcherHand, String batterHand, LocalDate asOf) {
        return jdbc.query(
            ARSENAL_SQL,
            (rs, n) -> new PitchArsenalDto(
                rs.getString("pitch_type"),
                toDouble(rs.getBigDecimal("usage_rate")),
                toDouble(rs.getBigDecimal("league_xwoba")),
                toDouble(rs.getBigDecimal("xwoba_against")),
                toDouble(rs.getBigDecimal("whiff_rate")),
                toDouble(rs.getBigDecimal("avg_velocity"))),
            pitcherHand, pitcherId, batterHand, pitcherId, batterHand, asOf);
    }

    // ── one batter's raw per-pitch-type xwOBA vs a pitcher hand ──
    public record BatterPitchRow(String pitchType, Double rawXwoba, int pitchesSeen, Double leagueXwoba) {}

    private static final String BATTER_PITCH_SQL = """
        SELECT s.pitch_type, s.xwoba, s.pitches_seen, b.league_xwoba
        FROM batter_pitch_type_stats s
        LEFT JOIN pitch_type_league_baselines b
          ON b.season = s.season AND b.pitch_type = s.pitch_type AND b.vs_handedness = s.vs_handedness
        WHERE s.player_id = ? AND s.vs_handedness = ?
          AND (s.season, s.as_of_date) = (
              SELECT season, as_of_date FROM batter_pitch_type_stats
              WHERE player_id = ? AND vs_handedness = ? AND as_of_date <= ?
              ORDER BY as_of_date DESC, season DESC LIMIT 1
          )
        """;

    public List<BatterPitchRow> batterPitchStats(int batterId, String pitcherHand, LocalDate asOf) {
        return jdbc.query(
            BATTER_PITCH_SQL,
            (rs, n) -> new BatterPitchRow(
                rs.getString("pitch_type"),
                toDouble(rs.getBigDecimal("xwoba")),
                rs.getInt("pitches_seen"),
                toDouble(rs.getBigDecimal("league_xwoba"))),
            batterId, pitcherHand, batterId, pitcherHand, asOf);
    }

    // ── leaderboard: batters playing on `date` vs a given pitch type ──
    public record LeaderboardRow(
        int playerId, String playerName, String teamAbbr,
        int pitcherId, String pitcherName, String pitcherThrows,
        double usageRate, Double rawXwoba, int pitchesSeen, Double leagueXwoba) {}

    private static final String LEADERBOARD_SQL = """
        SELECT
            p.id AS player_id, p.full_name AS player_name, t.abbreviation AS team_abbr,
            pit.id AS pitcher_id, pit.full_name AS pitcher_name, pit.throws AS pitcher_throws,
            ars.usage_rate, bs.xwoba AS raw_xwoba, bs.pitches_seen, lb.league_xwoba
        FROM batter_projections bp
        JOIN games g    ON g.id = bp.game_id AND g.game_date = ?
        JOIN players p  ON p.id = bp.player_id
        JOIN players pit ON pit.id = bp.opposing_pitcher_id
        JOIN teams t    ON t.id = (CASE WHEN bp.is_home THEN g.home_team_id ELSE g.away_team_id END)
        JOIN pitcher_arsenal ars
          ON ars.player_id = bp.opposing_pitcher_id
         AND ars.pitch_type = ?
         AND ars.vs_handedness = (CASE WHEN p.bats = 'S'
                                       THEN (CASE WHEN pit.throws = 'R' THEN 'L' ELSE 'R' END)
                                       ELSE p.bats END)
         AND (ars.season, ars.as_of_date) = (
              SELECT season, as_of_date FROM pitcher_arsenal
              WHERE player_id = bp.opposing_pitcher_id AND vs_handedness = ars.vs_handedness
                AND as_of_date <= g.game_date
              ORDER BY as_of_date DESC, season DESC LIMIT 1)
        JOIN batter_pitch_type_stats bs
          ON bs.player_id = bp.player_id
         AND bs.pitch_type = ?
         AND bs.vs_handedness = pit.throws
         AND (bs.season, bs.as_of_date) = (
              SELECT season, as_of_date FROM batter_pitch_type_stats
              WHERE player_id = bp.player_id AND vs_handedness = pit.throws
                AND as_of_date <= g.game_date
              ORDER BY as_of_date DESC, season DESC LIMIT 1)
        LEFT JOIN pitch_type_league_baselines lb
          ON lb.season = bs.season AND lb.pitch_type = ? AND lb.vs_handedness = pit.throws
        WHERE ars.usage_rate >= 0.20 AND bs.pitches_seen >= 100
        """;

    public List<LeaderboardRow> leaderboardCandidates(String pitch, LocalDate date) {
        return jdbc.query(
            LEADERBOARD_SQL,
            (rs, n) -> new LeaderboardRow(
                rs.getInt("player_id"), rs.getString("player_name"), rs.getString("team_abbr"),
                rs.getInt("pitcher_id"), rs.getString("pitcher_name"), rs.getString("pitcher_throws"),
                rs.getBigDecimal("usage_rate").doubleValue(),
                toDouble(rs.getBigDecimal("raw_xwoba")), rs.getInt("pitches_seen"),
                toDouble(rs.getBigDecimal("league_xwoba"))),
            date, pitch, pitch, pitch);
    }

    private static Double toDouble(BigDecimal bd) {
        return bd == null ? null : bd.doubleValue();
    }
}
