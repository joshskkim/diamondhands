package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.Array;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;

/**
 * Reads the Monte-Carlo game simulator's outputs (game_sim_projections) joined to team
 * abbreviations and the consensus book lines (game_odds) for the "Most Likely" board:
 * full-game totals vs the line, first-five-innings (F5) markets, NRFI/YRFI, and the
 * top player props (batter_projections).
 */
@Repository
public class MostLikelyRepository {

    private final JdbcTemplate jdbc;

    public MostLikelyRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // One row per game: sim distributions + consensus (avg) book lines for the
    // full-game total, the F5 total, and the first-inning total.
    private static final String SIM_SQL = """
        SELECT gsp.game_id, ht.abbreviation AS home_abbr, at2.abbreviation AS away_abbr,
               gsp.n_sims,
               gsp.expected_total, gsp.expected_home_runs, gsp.expected_away_runs,
               gsp.p_home_win, gsp.total_hist,
               gsp.f5_expected_total, gsp.f5_p_home_lead, gsp.f5_p_away_lead,
               gsp.f5_p_tie, gsp.f5_total_hist,
               gsp.p_yrfi,
               (SELECT AVG(line) FROM game_odds o
                  WHERE o.game_id = gsp.game_id AND o.market = 'total'    AND o.side = 'over') AS book_total,
               (SELECT AVG(line) FROM game_odds o
                  WHERE o.game_id = gsp.game_id AND o.market = 'total_f5' AND o.side = 'over') AS book_f5_total
        FROM game_sim_projections gsp
        JOIN games g  ON g.id  = gsp.game_id
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at2 ON at2.id = g.away_team_id
        WHERE g.game_date = ?
        ORDER BY gsp.game_id
        """;

    // Per-batter model probabilities across the slate (for prop leaderboards).
    private static final String PROPS_SQL = """
        SELECT bp.player_id, p.full_name, t.abbreviation AS team_abbr,
               at2.abbreviation AS away_abbr, ht.abbreviation AS home_abbr,
               bp.p_hit_1plus, bp.p_hr, bp.p_k_1plus, bp.expected_total_bases
        FROM batter_projections bp
        JOIN games g   ON g.id = bp.game_id
        JOIN players p ON p.id = bp.player_id
        JOIN teams t   ON t.id = CASE WHEN bp.is_home THEN g.home_team_id ELSE g.away_team_id END
        JOIN teams ht  ON ht.id = g.home_team_id
        JOIN teams at2 ON at2.id = g.away_team_id
        WHERE g.game_date = ?
        """;

    public List<SimRow> findSimRows(LocalDate date) {
        return jdbc.query(SIM_SQL, this::mapSim, date);
    }

    public List<PropRow> findPropRows(LocalDate date) {
        return jdbc.query(PROPS_SQL, this::mapProp, date);
    }

    private SimRow mapSim(ResultSet rs, int n) throws SQLException {
        return new SimRow(
            rs.getLong("game_id"),
            rs.getString("away_abbr") + " @ " + rs.getString("home_abbr"),
            rs.getString("home_abbr"),
            rs.getString("away_abbr"),
            rs.getInt("n_sims"),
            rs.getDouble("expected_total"),
            rs.getDouble("p_home_win"),
            toIntArray(rs.getArray("total_hist")),
            rs.getDouble("f5_expected_total"),
            rs.getDouble("f5_p_home_lead"),
            rs.getDouble("f5_p_away_lead"),
            rs.getDouble("f5_p_tie"),
            toIntArray(rs.getArray("f5_total_hist")),
            rs.getDouble("p_yrfi"),
            toDouble(rs.getBigDecimal("book_total")),
            toDouble(rs.getBigDecimal("book_f5_total")));
    }

    private PropRow mapProp(ResultSet rs, int n) throws SQLException {
        return new PropRow(
            rs.getInt("player_id"),
            rs.getString("full_name"),
            rs.getString("team_abbr"),
            rs.getString("away_abbr") + " @ " + rs.getString("home_abbr"),
            toDouble(rs.getBigDecimal("p_hit_1plus")),
            toDouble(rs.getBigDecimal("p_hr")),
            toDouble(rs.getBigDecimal("p_k_1plus")),
            toDouble(rs.getBigDecimal("expected_total_bases")));
    }

    private static int[] toIntArray(Array a) throws SQLException {
        if (a == null) return new int[0];
        Object raw = a.getArray();
        if (raw instanceof Integer[] boxed) {
            int[] out = new int[boxed.length];
            for (int i = 0; i < boxed.length; i++) out[i] = boxed[i] == null ? 0 : boxed[i];
            return out;
        }
        if (raw instanceof Number[] nums) {
            int[] out = new int[nums.length];
            for (int i = 0; i < nums.length; i++) out[i] = nums[i] == null ? 0 : nums[i].intValue();
            return out;
        }
        return new int[0];
    }

    private static Double toDouble(BigDecimal bd) {
        return bd == null ? null : bd.doubleValue();
    }

    public record SimRow(
        long gameId, String matchup, String homeAbbr, String awayAbbr, int nSims,
        double expectedTotal, double pHomeWin, int[] totalHist,
        double f5Total, double f5PHomeLead, double f5PAwayLead, double f5PTie, int[] f5TotalHist,
        double pYrfi, Double bookTotal, Double bookF5Total) {}

    public record PropRow(
        int playerId, String player, String team, String matchup,
        Double pHit1, Double pHr, Double pK1, Double expectedTb) {}
}
