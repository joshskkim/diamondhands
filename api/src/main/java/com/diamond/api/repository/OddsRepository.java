package com.diamond.api.repository;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.Array;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Reads stored sportsbook odds (game_odds / player_prop_odds) joined to the context the
 * odds service needs to compute best lines + model edge: team abbreviations, projected
 * team runs (game_projections), and per-batter model probabilities (batter_projections).
 */
@Repository
public class OddsRepository {

    private static final ObjectMapper WORKLOAD_JSON = new ObjectMapper();
    private static final TypeReference<Map<String, Double>> LADDER_TYPE = new TypeReference<>() {};

    private final JdbcTemplate jdbc;

    public OddsRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final String GAME_ODDS_SQL = """
        SELECT market, side, line, bookmaker, price_american, price_decimal, implied_prob
        FROM game_odds
        WHERE game_id = ?
        ORDER BY market, side, price_decimal DESC, bookmaker
        """;

    // Every model source that can price a quoted prop, joined to the quote itself. Which
    // column answers which market lives in OddsService.propOverProb:
    //   batter_projections      → hit / hr / bb (closed-form occurrence probs)
    //   game_sim_batter_props   → tb / hrr      (simulator histograms, any half-line)
    //   pitcher_projections     → pitcher_k / pitcher_outs (workload ladder, fixed lines)
    //   game_sim_pitcher_props  → pitcher_hits_allowed / pitcher_earned_runs (histograms)
    // A player_id is a batter's or a pitcher's, never both, so the batter- and
    // pitcher-side joins are mutually exclusive and each row carries exactly one model.
    private static final String PROP_MODEL_COLUMNS = """
               bp.p_hit_1plus, bp.p_hit_2plus, bp.p_hr, bp.p_bb_1plus,
               sbp.n_sims AS sbp_n_sims, sbp.tb_hist, sbp.hrr_hist,
               pp.workload->'p_k'    AS workload_p_k,
               pp.workload->'p_outs' AS workload_p_outs,
               spp.n_sims AS spp_n_sims, spp.hits_hist, spp.er_hist
        """;

    private static final String PROP_MODEL_JOINS = """
        LEFT JOIN batter_projections bp
               ON bp.game_id = po.game_id AND bp.player_id = po.player_id
        LEFT JOIN game_sim_batter_props sbp
               ON sbp.game_id = po.game_id AND sbp.player_id = po.player_id
        LEFT JOIN pitcher_projections pp
               ON pp.game_id = po.game_id AND pp.pitcher_id = po.player_id
        LEFT JOIN game_sim_pitcher_props spp
               ON spp.game_id = po.game_id AND spp.pitcher_id = po.player_id
        """;

    private static final String PROP_ODDS_SQL = """
        SELECT po.player_id, po.player_name, p.bats, p.position,
               po.market, po.side, po.line, po.bookmaker,
               po.price_american, po.price_decimal, po.implied_prob,
        %s
        FROM player_prop_odds po
        JOIN players p ON p.id = po.player_id
        %s
        WHERE po.game_id = ?
        ORDER BY po.market, po.player_name, po.line, po.side, po.price_decimal DESC, po.bookmaker
        """.formatted(PROP_MODEL_COLUMNS, PROP_MODEL_JOINS);

    private static final String RUN_PROJ_SQL = """
        SELECT expected_home_runs, expected_away_runs
        FROM game_projections WHERE game_id = ?
        """;

    private static final String META_SQL = """
        SELECT ht.abbreviation AS home_abbr, at2.abbreviation AS away_abbr
        FROM games g
        JOIN teams ht  ON ht.id  = g.home_team_id
        JOIN teams at2 ON at2.id = g.away_team_id
        WHERE g.id = ?
        """;

    private static final String GAME_IDS_SQL = """
        SELECT id FROM games g
        WHERE game_date = ? AND odds_event_id IS NOT NULL
          AND %s
        ORDER BY start_time_utc
        """.formatted(GameStatus.livePredicate("g"));

    public List<GameOddRow> findGameOdds(long gameId) {
        return jdbc.query(GAME_ODDS_SQL, this::mapGameOdd, gameId);
    }

    public List<PropOddRow> findPropOdds(long gameId) {
        return jdbc.query(PROP_ODDS_SQL, this::mapPropOdd, gameId);
    }

    /** Projected (home, away) runs, or null if the game has no projection. */
    public RunProj findRunProj(long gameId) {
        return jdbc.query(RUN_PROJ_SQL, rs -> rs.next()
            ? new RunProj(rs.getDouble("expected_home_runs"), rs.getDouble("expected_away_runs"))
            : null, gameId);
    }

    public GameMeta findGameMeta(long gameId) {
        return jdbc.query(META_SQL, rs -> rs.next()
            ? new GameMeta(rs.getString("home_abbr"), rs.getString("away_abbr"))
            : null, gameId);
    }

    /** The game's slate date — the "as of" cutoff for a player's clear rates. */
    public LocalDate findGameDate(long gameId) {
        return jdbc.query("SELECT game_date FROM games WHERE id = ?",
            rs -> rs.next() ? rs.getObject("game_date", LocalDate.class) : null, gameId);
    }

    public List<Long> findGameIdsWithOdds(LocalDate date) {
        return jdbc.queryForList(GAME_IDS_SQL, Long.class, date);
    }

    // ── Date-scoped batch reads for bestPlays() ──────────────────────────────────────
    // bestPlays() used to call the four per-game reads above once per game (an N+1 over the
    // slate's games). These fetch the whole slate in one query each, keyed by game_id; the
    // per-game row order matches the single-game queries so the built responses are identical.

    private static final String GAME_ODDS_BY_DATE_SQL = """
        SELECT go.game_id, go.market, go.side, go.line, go.bookmaker,
               go.price_american, go.price_decimal, go.implied_prob
        FROM game_odds go
        JOIN games g ON g.id = go.game_id AND g.game_date = ?
        ORDER BY go.game_id, go.market, go.side, go.price_decimal DESC, go.bookmaker
        """;

    // Slate-wide form of PROP_ODDS_SQL — same model joins, or /api/odds/best would price
    // fewer markets than the per-game panel.
    private static final String PROP_ODDS_BY_DATE_SQL = """
        SELECT po.game_id, po.player_id, po.player_name, p.bats, p.position,
               po.market, po.side, po.line, po.bookmaker,
               po.price_american, po.price_decimal, po.implied_prob,
        %s
        FROM player_prop_odds po
        JOIN games g ON g.id = po.game_id AND g.game_date = ?
        JOIN players p ON p.id = po.player_id
        %s
        ORDER BY po.game_id, po.market, po.player_name, po.line, po.side, po.price_decimal DESC, po.bookmaker
        """.formatted(PROP_MODEL_COLUMNS, PROP_MODEL_JOINS);

    private static final String RUN_PROJ_BY_DATE_SQL = """
        SELECT gp.game_id, gp.expected_home_runs, gp.expected_away_runs
        FROM game_projections gp
        JOIN games g ON g.id = gp.game_id AND g.game_date = ?
        """;

    private static final String META_BY_DATE_SQL = """
        SELECT g.id AS game_id, ht.abbreviation AS home_abbr, at2.abbreviation AS away_abbr
        FROM games g
        JOIN teams ht  ON ht.id  = g.home_team_id
        JOIN teams at2 ON at2.id = g.away_team_id
        WHERE g.game_date = ?
        """;

    public Map<Long, List<GameOddRow>> findGameOddsByDate(LocalDate date) {
        return jdbc.query(GAME_ODDS_BY_DATE_SQL, rs -> {
            Map<Long, List<GameOddRow>> out = new HashMap<>();
            while (rs.next()) {
                out.computeIfAbsent(rs.getLong("game_id"), k -> new ArrayList<>()).add(mapGameOdd(rs, 0));
            }
            return out;
        }, date);
    }

    public Map<Long, List<PropOddRow>> findPropOddsByDate(LocalDate date) {
        return jdbc.query(PROP_ODDS_BY_DATE_SQL, rs -> {
            Map<Long, List<PropOddRow>> out = new HashMap<>();
            while (rs.next()) {
                out.computeIfAbsent(rs.getLong("game_id"), k -> new ArrayList<>()).add(mapPropOdd(rs, 0));
            }
            return out;
        }, date);
    }

    public Map<Long, RunProj> findRunProjByDate(LocalDate date) {
        return jdbc.query(RUN_PROJ_BY_DATE_SQL, rs -> {
            Map<Long, RunProj> out = new HashMap<>();
            while (rs.next()) {
                out.put(rs.getLong("game_id"),
                    new RunProj(rs.getDouble("expected_home_runs"), rs.getDouble("expected_away_runs")));
            }
            return out;
        }, date);
    }

    public Map<Long, GameMeta> findGameMetaByDate(LocalDate date) {
        return jdbc.query(META_BY_DATE_SQL, rs -> {
            Map<Long, GameMeta> out = new HashMap<>();
            while (rs.next()) {
                out.put(rs.getLong("game_id"),
                    new GameMeta(rs.getString("home_abbr"), rs.getString("away_abbr")));
            }
            return out;
        }, date);
    }

    // ── Analyst verdicts for the slate (the promotion gate, see V64) ──
    // Keyed by selection identity (line excluded, like model_picks/pick_verdicts identity) so a
    // line move keeps the verdict. The board joins this to gate + annotate; a missing key means
    // "not vetted" (show mechanically).
    public record VerdictRow(String verdict, Double confidence, String rationale) {}

    private static final String PICK_VERDICTS_SQL = """
        SELECT game_id, market, side, player_id, verdict, confidence, rationale
        FROM pick_verdicts
        WHERE slate_date = ?
        """;

    public Map<String, VerdictRow> findPickVerdictsByDate(LocalDate date) {
        return jdbc.query(PICK_VERDICTS_SQL, rs -> {
            Map<String, VerdictRow> out = new HashMap<>();
            while (rs.next()) {
                Integer pid = rs.getObject("player_id") == null ? null : rs.getInt("player_id");
                String key = verdictKey(rs.getLong("game_id"), rs.getString("market"),
                    rs.getString("side"), pid);
                BigDecimal conf = rs.getBigDecimal("confidence");
                out.put(key, new VerdictRow(rs.getString("verdict"),
                    conf == null ? null : conf.doubleValue(), rs.getString("rationale")));
            }
            return out;
        }, date);
    }

    /** Selection key for joining a verdict onto a best-play row (line excluded). */
    public static String verdictKey(long gameId, String market, String side, Integer playerId) {
        return gameId + ":" + market + ":" + side + ":" + (playerId == null ? "" : playerId);
    }

    // ── slate-wide batter prop over-prices, one row per game+player+market ──
    // Best (highest decimal = best for the bettor) price across the books we ingest
    // (FanDuel / DraftKings / Fanatics). We no longer pin a single preferred book.
    private static final String BATTER_PROPS_SQL = """
        SELECT DISTINCT ON (po.game_id, po.player_id, po.market)
            po.game_id, po.player_id, po.market, po.line,
            po.bookmaker, po.price_american, po.price_decimal
        FROM player_prop_odds po
        JOIN games g ON g.id = po.game_id AND g.game_date = ?
        WHERE po.side = 'over' AND po.market IN ('hit', 'hr') AND po.line = 0.5
        ORDER BY po.game_id, po.player_id, po.market, po.price_decimal DESC
        """;

    // ── Multi-book line shopping (props) ──
    // Every book's posted price for each prop selection on the slate, best (highest
    // decimal = best for the bettor) first within a selection, so the service can group
    // consecutive rows into a per-selection ladder.
    private static final String PROP_QUOTES_SQL = """
        SELECT po.game_id, po.player_id, po.market, po.side, po.line,
               po.bookmaker, po.price_american, po.price_decimal
        FROM player_prop_odds po
        JOIN games g ON g.id = po.game_id AND g.game_date = ?
        ORDER BY po.game_id, po.player_id, po.market, po.side, po.line,
                 po.price_decimal DESC
        """;

    public List<PropQuoteRow> findPropQuotes(LocalDate date) {
        return jdbc.query(PROP_QUOTES_SQL, (rs, n) -> new PropQuoteRow(
                rs.getLong("game_id"),
                rs.getInt("player_id"),
                rs.getString("market"),
                rs.getString("side"),
                rs.getBigDecimal("line").doubleValue(),
                rs.getString("bookmaker"),
                rs.getInt("price_american"),
                rs.getBigDecimal("price_decimal").doubleValue()),
            date);
    }

    // ── Outlier-style hit-rate "traffic light" ──
    // For every batter that has a hit/HR prop on the slate, how often they've cleared
    // that prop's line over their last 5/10/20 games and the current season. The line
    // comes from the prop itself (almost always 0.5 = "to record one"), so this answers
    // exactly the question the prop asks. Trailing windows are rolling and may cross a
    // season boundary (a player's literal last N games); the season rate is calendar-year.
    private static final String HIT_RATES_SQL = """
        WITH prop_players AS (
            SELECT po.player_id, po.market, MIN(po.line) AS line
            FROM player_prop_odds po
            JOIN games g ON g.id = po.game_id AND g.game_date = ?
            WHERE po.market IN ('hit', 'hr')
            GROUP BY po.player_id, po.market
        ),
        recent AS (
            SELECT pp.player_id, pp.market, pp.line, pgs.game_date,
                   CASE pp.market
                       WHEN 'hit' THEN (pgs.hits      > pp.line)::int
                       WHEN 'hr'  THEN (pgs.home_runs > pp.line)::int
                   END AS cleared,
                   row_number() OVER (
                       PARTITION BY pp.player_id, pp.market
                       ORDER BY pgs.game_date DESC, pgs.game_id DESC
                   ) AS rn
            FROM prop_players pp
            JOIN player_game_stats pgs
                 ON pgs.player_id = pp.player_id
                AND pgs.game_date < ?
                AND pgs.plate_appearances > 0
        )
        SELECT player_id, market, line,
            avg(cleared::numeric) FILTER (WHERE rn <= 5)            AS l5,
            avg(cleared::numeric) FILTER (WHERE rn <= 10)           AS l10,
            avg(cleared::numeric) FILTER (WHERE rn <= 20)           AS l20,
            count(*)              FILTER (WHERE rn <= 20)           AS n20,
            avg(cleared::numeric) FILTER (WHERE game_date >= ?)     AS season,
            count(*)              FILTER (WHERE game_date >= ?)     AS n_season
        FROM recent
        GROUP BY player_id, market, line
        """;

    public List<HitRateRow> findHitRates(LocalDate date, LocalDate seasonStart) {
        return jdbc.query(HIT_RATES_SQL, (rs, n) -> new HitRateRow(
                rs.getInt("player_id"),
                rs.getString("market"),
                rs.getBigDecimal("line").doubleValue(),
                toDouble(rs.getBigDecimal("l5")),
                toDouble(rs.getBigDecimal("l10")),
                toDouble(rs.getBigDecimal("l20")),
                rs.getInt("n20"),
                toDouble(rs.getBigDecimal("season")),
                rs.getInt("n_season")),
            date, date, seasonStart, seasonStart);
    }

    public List<BatterPropRow> findBatterProps(LocalDate date) {
        return jdbc.query(BATTER_PROPS_SQL, (rs, n) -> new BatterPropRow(
            rs.getLong("game_id"),
            rs.getInt("player_id"),
            rs.getString("market"),
            toDouble(rs.getBigDecimal("line")),
            rs.getString("bookmaker"),
            rs.getInt("price_american"),
            rs.getBigDecimal("price_decimal").doubleValue()),
            date);
    }

    private GameOddRow mapGameOdd(ResultSet rs, int n) throws SQLException {
        return new GameOddRow(
            rs.getString("market"),
            rs.getString("side"),
            toDouble(rs.getBigDecimal("line")),
            rs.getString("bookmaker"),
            rs.getInt("price_american"),
            rs.getBigDecimal("price_decimal").doubleValue(),
            rs.getBigDecimal("implied_prob").doubleValue());
    }

    private PropOddRow mapPropOdd(ResultSet rs, int n) throws SQLException {
        return new PropOddRow(
            rs.getInt("player_id"),
            rs.getString("player_name"),
            rs.getString("bats"),
            rs.getString("position"),
            rs.getString("market"),
            rs.getString("side"),
            rs.getBigDecimal("line").doubleValue(),
            rs.getString("bookmaker"),
            rs.getInt("price_american"),
            rs.getBigDecimal("price_decimal").doubleValue(),
            rs.getBigDecimal("implied_prob").doubleValue(),
            mapPropModel(rs));
    }

    private PropModelRow mapPropModel(ResultSet rs) throws SQLException {
        return new PropModelRow(
            toDouble(rs.getBigDecimal("p_hit_1plus")),
            toDouble(rs.getBigDecimal("p_hit_2plus")),
            toDouble(rs.getBigDecimal("p_hr")),
            toDouble(rs.getBigDecimal("p_bb_1plus")),
            (Integer) rs.getObject("sbp_n_sims"),
            toIntArray(rs.getArray("tb_hist")),
            toIntArray(rs.getArray("hrr_hist")),
            toLadder(rs.getString("workload_p_k")),
            toLadder(rs.getString("workload_p_outs")),
            (Integer) rs.getObject("spp_n_sims"),
            toIntArray(rs.getArray("hits_hist")),
            toIntArray(rs.getArray("er_hist")));
    }

    /** A workload threshold ladder ({"5.5": 0.42, …}) out of the `workload` jsonb. */
    private static Map<String, Double> toLadder(String json) {
        if (json == null || json.isBlank()) return null;
        try {
            return WORKLOAD_JSON.readValue(json, LADDER_TYPE);
        } catch (JsonProcessingException e) {
            return null;
        }
    }

    private static int[] toIntArray(Array a) throws SQLException {
        if (a == null) return new int[0];
        Object raw = a.getArray();
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

    public record GameOddRow(
        String market, String side, Double line, String bookmaker,
        int priceAmerican, double priceDecimal, double impliedProb) {}

    public record PropOddRow(
        int playerId, String playerName, String bats, String position,
        String market, String side, double line, String bookmaker,
        int priceAmerican, double priceDecimal, double impliedProb,
        PropModelRow model) {}

    /**
     * The model's view of one quoted prop: whichever of the four projection sources
     * covers this player's markets. All fields are nullable — a batter carries the
     * batter columns and nulls on the pitcher side, and a player with no projection at
     * all (scratched, no sim row) carries nulls throughout, which
     * {@code OddsService.propOverProb} turns into "no model" rather than a bogus 0%.
     *
     * <p>{@code pK} / {@code pOuts} are the workload model's threshold ladders keyed by
     * line ("5.5" → p); they only hold the lines projection/workload.py materialized.
     */
    public record PropModelRow(
        Double pHit1, Double pHit2, Double pHr, Double pBb1,
        Integer simNSims, int[] tbHist, int[] hrrHist,
        Map<String, Double> pK, Map<String, Double> pOuts,
        Integer pitcherNSims, int[] hitsHist, int[] erHist) {

        // A record's generated equals() compares array fields by reference, which would make
        // two rows read from identical DB state unequal. RepositoryBatchEquivalenceTest
        // compares these by value to prove the batch query matches the per-game one.
        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof PropModelRow r)) return false;
            return Objects.equals(pHit1, r.pHit1) && Objects.equals(pHit2, r.pHit2)
                && Objects.equals(pHr, r.pHr) && Objects.equals(pBb1, r.pBb1)
                && Objects.equals(simNSims, r.simNSims)
                && Arrays.equals(tbHist, r.tbHist) && Arrays.equals(hrrHist, r.hrrHist)
                && Objects.equals(pK, r.pK) && Objects.equals(pOuts, r.pOuts)
                && Objects.equals(pitcherNSims, r.pitcherNSims)
                && Arrays.equals(hitsHist, r.hitsHist) && Arrays.equals(erHist, r.erHist);
        }

        @Override
        public int hashCode() {
            return Objects.hash(pHit1, pHit2, pHr, pBb1, simNSims,
                Arrays.hashCode(tbHist), Arrays.hashCode(hrrHist), pK, pOuts,
                pitcherNSims, Arrays.hashCode(hitsHist), Arrays.hashCode(erHist));
        }
    }

    public record RunProj(double expHome, double expAway) {}

    public record GameMeta(String homeAbbr, String awayAbbr) {}

    public record BatterPropRow(
        long gameId, int playerId, String market, Double line,
        String bookmaker, int priceAmerican, double priceDecimal) {}

    public record HitRateRow(
        int playerId, String market, double line,
        Double l5, Double l10, Double l20, int n20,
        Double season, int nSeason) {}

    public record PropQuoteRow(
        long gameId, int playerId, String market, String side, double line,
        String bookmaker, int priceAmerican, double priceDecimal) {}
}
