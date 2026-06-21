package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Reads stored sportsbook odds (game_odds / player_prop_odds) joined to the context the
 * odds service needs to compute best lines + model edge: team abbreviations, projected
 * team runs (game_projections), and per-batter model probabilities (batter_projections).
 */
@Repository
public class OddsRepository {

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

    private static final String PROP_ODDS_SQL = """
        SELECT po.player_id, po.player_name, p.bats, p.position,
               po.market, po.side, po.line, po.bookmaker,
               po.price_american, po.price_decimal, po.implied_prob,
               bp.p_hit_1plus, bp.p_hit_2plus, bp.p_hr
        FROM player_prop_odds po
        JOIN players p ON p.id = po.player_id
        LEFT JOIN batter_projections bp
               ON bp.game_id = po.game_id AND bp.player_id = po.player_id
        WHERE po.game_id = ?
        ORDER BY po.market, po.player_name, po.line, po.side, po.price_decimal DESC, po.bookmaker
        """;

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
        SELECT id FROM games
        WHERE game_date = ? AND odds_event_id IS NOT NULL
        ORDER BY start_time_utc
        """;

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

    private static final String PROP_ODDS_BY_DATE_SQL = """
        SELECT po.game_id, po.player_id, po.player_name, p.bats, p.position,
               po.market, po.side, po.line, po.bookmaker,
               po.price_american, po.price_decimal, po.implied_prob,
               bp.p_hit_1plus, bp.p_hit_2plus, bp.p_hr
        FROM player_prop_odds po
        JOIN games g ON g.id = po.game_id AND g.game_date = ?
        JOIN players p ON p.id = po.player_id
        LEFT JOIN batter_projections bp
               ON bp.game_id = po.game_id AND bp.player_id = po.player_id
        ORDER BY po.game_id, po.market, po.player_name, po.line, po.side, po.price_decimal DESC, po.bookmaker
        """;

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
            toDouble(rs.getBigDecimal("p_hit_1plus")),
            toDouble(rs.getBigDecimal("p_hit_2plus")),
            toDouble(rs.getBigDecimal("p_hr")));
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
        Double pHit1, Double pHit2, Double pHr) {}

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
