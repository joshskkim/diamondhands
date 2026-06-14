package com.diamond.api.repository;

import com.diamond.api.dto.PitchArsenalDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

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

    // ── Batched forms for a whole game (≤2 opposing pitchers) ─────────────────────────
    // Each batter projection used to fire two snapshot queries (arsenal + batter pitch
    // stats) — an N+1 of ~2 queries per batter. These resolve each player's latest
    // snapshot once with a DISTINCT ON CTE (the same pattern proven on LEADERBOARD_SQL)
    // and fetch every batter/pitcher in one round-trip. Keys are "id|vs_handedness".

    private static String key(int id, String hand) {
        return id + "|" + hand;
    }

    // The single-row arsenal() joins the league baseline on the *pitcher's* throwing hand
    // (its first bind param), not the arsenal row's vs_handedness. We reproduce that exactly
    // via an unnest(pitcherId, pitcherHand) mapping so league_xwoba is byte-identical.
    private static final String ARSENAL_BATCH_SQL = """
        WITH ph AS (
            SELECT * FROM unnest(?::int[], ?::varchar[]) AS t(player_id, pitcher_hand)
        ),
        ars_snap AS (
            SELECT DISTINCT ON (player_id, vs_handedness)
                   player_id, vs_handedness, season, as_of_date
            FROM pitcher_arsenal
            WHERE player_id = ANY(?) AND vs_handedness = ANY(?) AND as_of_date <= ?
            ORDER BY player_id, vs_handedness, as_of_date DESC, season DESC
        )
        SELECT a.player_id, a.vs_handedness, a.pitch_type, a.usage_rate, a.xwoba_against,
               a.whiff_rate, a.avg_velocity, b.league_xwoba
        FROM pitcher_arsenal a
        JOIN ars_snap s ON s.player_id = a.player_id AND s.vs_handedness = a.vs_handedness
                       AND s.season = a.season AND s.as_of_date = a.as_of_date
        JOIN ph ON ph.player_id = a.player_id
        LEFT JOIN pitch_type_league_baselines b
          ON b.season = a.season AND b.pitch_type = a.pitch_type AND b.vs_handedness = ph.pitcher_hand
        ORDER BY a.player_id, a.vs_handedness, a.usage_rate DESC
        """;

    /** Arsenal per (pitcherId, batterHand), ordered by usage desc — keyed "pitcherId|batterHand".
     *  {@code pitcherHandById} maps each pitcher to its throwing hand (for the baseline join). */
    public Map<String, List<PitchArsenalDto>> arsenalBatch(
            Map<Integer, String> pitcherHandById, Collection<String> batterHands, LocalDate asOf) {
        if (pitcherHandById.isEmpty() || batterHands.isEmpty()) {
            return Map.of();
        }
        int n = pitcherHandById.size();
        Integer[] ids = new Integer[n];
        String[] pHands = new String[n];
        int i = 0;
        for (Map.Entry<Integer, String> e : pitcherHandById.entrySet()) {
            ids[i] = e.getKey();
            pHands[i] = e.getValue();
            i++;
        }
        String[] bHands = batterHands.toArray(new String[0]);
        return jdbc.query(
            con -> {
                PreparedStatement ps = con.prepareStatement(ARSENAL_BATCH_SQL);
                ps.setArray(1, con.createArrayOf("integer", ids));
                ps.setArray(2, con.createArrayOf("varchar", pHands));
                ps.setArray(3, con.createArrayOf("integer", ids));
                ps.setArray(4, con.createArrayOf("varchar", bHands));
                ps.setObject(5, asOf);
                return ps;
            },
            rs -> {
                Map<String, List<PitchArsenalDto>> out = new HashMap<>();
                while (rs.next()) {
                    String k = key(rs.getInt("player_id"), rs.getString("vs_handedness"));
                    out.computeIfAbsent(k, x -> new ArrayList<>()).add(new PitchArsenalDto(
                        rs.getString("pitch_type"),
                        toDouble(rs.getBigDecimal("usage_rate")),
                        toDouble(rs.getBigDecimal("league_xwoba")),
                        toDouble(rs.getBigDecimal("xwoba_against")),
                        toDouble(rs.getBigDecimal("whiff_rate")),
                        toDouble(rs.getBigDecimal("avg_velocity"))));
                }
                return out;
            });
    }

    private static final String BATTER_PITCH_BATCH_SQL = """
        WITH bs_snap AS (
            SELECT DISTINCT ON (player_id, vs_handedness)
                   player_id, vs_handedness, season, as_of_date
            FROM batter_pitch_type_stats
            WHERE player_id = ANY(?) AND vs_handedness = ANY(?) AND as_of_date <= ?
            ORDER BY player_id, vs_handedness, as_of_date DESC, season DESC
        )
        SELECT s.player_id, s.vs_handedness, s.pitch_type, s.xwoba, s.pitches_seen, b.league_xwoba
        FROM batter_pitch_type_stats s
        JOIN bs_snap sn ON sn.player_id = s.player_id AND sn.vs_handedness = s.vs_handedness
                       AND sn.season = s.season AND sn.as_of_date = s.as_of_date
        LEFT JOIN pitch_type_league_baselines b
          ON b.season = s.season AND b.pitch_type = s.pitch_type AND b.vs_handedness = s.vs_handedness
        """;

    /** Batter per-pitch-type rows keyed "batterId|pitcherHand", each as a pitchType→row map. */
    public Map<String, Map<String, BatterPitchRow>> batterPitchStatsBatch(
            Collection<Integer> batterIds, Collection<String> pitcherHands, LocalDate asOf) {
        if (batterIds.isEmpty() || pitcherHands.isEmpty()) {
            return Map.of();
        }
        Integer[] ids = batterIds.toArray(new Integer[0]);
        String[] hands = pitcherHands.toArray(new String[0]);
        return jdbc.query(
            con -> {
                PreparedStatement ps = con.prepareStatement(BATTER_PITCH_BATCH_SQL);
                ps.setArray(1, con.createArrayOf("integer", ids));
                ps.setArray(2, con.createArrayOf("varchar", hands));
                ps.setObject(3, asOf);
                return ps;
            },
            rs -> {
                Map<String, Map<String, BatterPitchRow>> out = new HashMap<>();
                while (rs.next()) {
                    String k = key(rs.getInt("player_id"), rs.getString("vs_handedness"));
                    out.computeIfAbsent(k, x -> new HashMap<>()).put(
                        rs.getString("pitch_type"),
                        new BatterPitchRow(
                            rs.getString("pitch_type"),
                            toDouble(rs.getBigDecimal("xwoba")),
                            rs.getInt("pitches_seen"),
                            toDouble(rs.getBigDecimal("league_xwoba"))));
                }
                return out;
            });
    }

    // ── leaderboard: batters playing on `date` vs a given pitch type ──
    public record LeaderboardRow(
        int playerId, String playerName, String teamAbbr,
        int pitcherId, String pitcherName, String pitcherThrows,
        double usageRate, Double rawXwoba, int pitchesSeen, Double leagueXwoba) {}

    // The original form expressed "latest (season, as_of_date) on/before the game date"
    // as a correlated subquery inside each JOIN ON clause. With both the arsenal and the
    // batter-pitch joins doing that, the planner produced a nested loop that re-evaluated
    // the subquery hundreds of thousands of times (~15s, 1.6M buffer hits, for a busy
    // pitch like FF). Since the whole leaderboard is pinned to a single date, we instead
    // resolve each player's latest snapshot once via DISTINCT ON CTEs, then join plainly.
    // Identical result set, ~10x faster (verified by row-level diff).
    private static final String LEADERBOARD_SQL = """
        WITH ars_snap AS (
            SELECT DISTINCT ON (player_id, vs_handedness)
                   player_id, vs_handedness, season, as_of_date
            FROM pitcher_arsenal
            WHERE as_of_date <= ?
            ORDER BY player_id, vs_handedness, as_of_date DESC, season DESC
        ),
        bs_snap AS (
            SELECT DISTINCT ON (player_id, vs_handedness)
                   player_id, vs_handedness, season, as_of_date
            FROM batter_pitch_type_stats
            WHERE as_of_date <= ?
            ORDER BY player_id, vs_handedness, as_of_date DESC, season DESC
        )
        SELECT
            p.id AS player_id, p.full_name AS player_name, t.abbreviation AS team_abbr,
            pit.id AS pitcher_id, pit.full_name AS pitcher_name, pit.throws AS pitcher_throws,
            ars.usage_rate, bs.xwoba AS raw_xwoba, bs.pitches_seen, lb.league_xwoba
        FROM batter_projections bp
        JOIN games g    ON g.id = bp.game_id AND g.game_date = ?
        JOIN players p  ON p.id = bp.player_id
        JOIN players pit ON pit.id = bp.opposing_pitcher_id
        JOIN teams t    ON t.id = (CASE WHEN bp.is_home THEN g.home_team_id ELSE g.away_team_id END)
        JOIN ars_snap asn
          ON asn.player_id = bp.opposing_pitcher_id
         AND asn.vs_handedness = (CASE WHEN p.bats = 'S'
                                       THEN (CASE WHEN pit.throws = 'R' THEN 'L' ELSE 'R' END)
                                       ELSE p.bats END)
        JOIN pitcher_arsenal ars
          ON ars.player_id = asn.player_id AND ars.vs_handedness = asn.vs_handedness
         AND ars.season = asn.season AND ars.as_of_date = asn.as_of_date
         AND ars.pitch_type = ?
        JOIN bs_snap bsn
          ON bsn.player_id = bp.player_id AND bsn.vs_handedness = pit.throws
        JOIN batter_pitch_type_stats bs
          ON bs.player_id = bsn.player_id AND bs.vs_handedness = bsn.vs_handedness
         AND bs.season = bsn.season AND bs.as_of_date = bsn.as_of_date
         AND bs.pitch_type = ?
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
            date, date, date, pitch, pitch, pitch);
    }

    private static Double toDouble(BigDecimal bd) {
        return bd == null ? null : bd.doubleValue();
    }
}
