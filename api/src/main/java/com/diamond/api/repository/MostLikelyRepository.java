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
 * full-game totals vs the line, run-line (±1.5) cover leans, NRFI/YRFI, and the
 * top player props (batter_projections).
 */
@Repository
public class MostLikelyRepository {

    private final JdbcTemplate jdbc;

    public MostLikelyRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // One row per game: sim distributions + consensus (avg) book data for the full-game
    // total and the ±1.5 run line. Run-line book implied probs are split by the -1.5
    // (favorite covers) and +1.5 (underdog covers) sides so the service can de-vig.
    private static final String SIM_SQL = """
        SELECT gsp.game_id, ht.abbreviation AS home_abbr, at2.abbreviation AS away_abbr,
               gsp.n_sims,
               gsp.expected_total,
               gsp.p_home_win, gsp.total_hist,
               gsp.p_home_cover_1_5, gsp.p_away_cover_1_5, gsp.p_home_cover_plus15,
               gsp.p_yrfi,
               (SELECT AVG(line) FROM game_odds o
                  WHERE o.game_id = gsp.game_id AND o.market = 'total' AND o.side = 'over') AS book_total,
               (SELECT AVG(implied_prob) FROM game_odds o
                  WHERE o.game_id = gsp.game_id AND o.market = 'run_line' AND o.line = -1.5) AS book_fav_implied,
               (SELECT AVG(implied_prob) FROM game_odds o
                  WHERE o.game_id = gsp.game_id AND o.market = 'run_line' AND o.line = 1.5)  AS book_dog_implied,
               -- Which side the book lays -1.5 on (its favorite). Lets the service pick the
               -- sim's cover prob for the RIGHT team when it's the away side, rather than
               -- assuming the sim and book agree on who's favored.
               (SELECT o.side FROM game_odds o
                  WHERE o.game_id = gsp.game_id AND o.market = 'run_line' AND o.line = -1.5
                  GROUP BY o.side ORDER BY COUNT(*) DESC LIMIT 1) AS book_fav_side
        FROM game_sim_projections gsp
        JOIN games g  ON g.id  = gsp.game_id
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at2 ON at2.id = g.away_team_id
        WHERE g.game_date = ?
          AND %s
        ORDER BY gsp.game_id
        """.formatted(GameStatus.livePredicate("g"));

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
          AND %s
        """.formatted(GameStatus.livePredicate("g"));

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
            rs.getDouble("p_home_cover_1_5"),
            rs.getDouble("p_away_cover_1_5"),
            toDouble(rs.getBigDecimal("p_home_cover_plus15")),
            rs.getDouble("p_yrfi"),
            toDouble(rs.getBigDecimal("book_total")),
            toDouble(rs.getBigDecimal("book_fav_implied")),
            toDouble(rs.getBigDecimal("book_dog_implied")),
            rs.getString("book_fav_side"));
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
        double pHomeCover15, double pAwayCover15,
        // P(home covers +1.5) — the underdog-side prob when home is the dog. Null on
        // rows projected before V69 added the column (run-line falls back then).
        Double pHomeCoverPlus15,
        double pYrfi, Double bookTotal, Double bookFavImplied, Double bookDogImplied,
        // "home"/"away": which team the book lays -1.5 on. Null when no run-line odds.
        String bookFavSide) {}

    public record PropRow(
        int playerId, String player, String team, String matchup,
        Double pHit1, Double pHr, Double pK1, Double expectedTb) {}
}
