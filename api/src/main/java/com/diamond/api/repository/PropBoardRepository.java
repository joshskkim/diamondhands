package com.diamond.api.repository;

import com.diamond.api.dto.PitcherPropPickDto;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Array;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Reads the mechanistic model's batter projections (batter_projections) with the full
 * explanation context — opposing pitcher, matchup quality, park/pitcher/weather
 * adjustments, lineup slot — for the model-first prop board. Unlike the odds board,
 * none of this depends on sportsbook data: cached best prices are attached separately
 * and may be absent.
 */
@Repository
public class PropBoardRepository {

    private static final ObjectMapper ARSENAL_JSON = new ObjectMapper();
    private static final TypeReference<List<PitcherPropPickDto.ArsenalPitch>> ARSENAL_TYPE =
        new TypeReference<>() {};

    private final JdbcTemplate jdbc;

    public PropBoardRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // Every projected batter on the slate with the factors that explain the number.
    private static final String SLATE_SQL = """
        SELECT bp.game_id, at2.abbreviation || ' @ ' || ht.abbreviation AS matchup,
               bp.player_id, p.full_name, t.abbreviation AS team_abbr,
               bp.lineup_position, bp.lineup_confirmed, bp.expected_pa,
               bp.p_hit_1plus, bp.p_hr, bp.p_k_1plus, bp.p_bb_1plus,
               sbp.p_hit_1plus AS sim_hit, sbp.p_hr AS sim_hr, sbp.p_k_1plus AS sim_k,
               sbp.n_sims AS sim_n_sims, sbp.expected_tb AS sim_expected_tb,
               sbp.expected_hrr AS sim_expected_hrr, sbp.tb_hist, sbp.hrr_hist,
               bp.adj_park, bp.adj_pitcher, bp.adj_weather_hr, bp.adj_weather_hits, bp.adj_defense,
               bp.matchup_xwoba, bp.matchup_quality, bp.pitcher_data_quality,
               bp.opposing_pitcher_id, op.full_name AS opposing_pitcher,
               s.name AS stadium,
               COALESCE(p.bats, 'R') AS bats,
               s.lf_line_ft, s.lf_wall_ft, s.rf_line_ft, s.rf_wall_ft,
               bb.pull_pct, bb.fb_pct, bb.avg_launch_speed,
               bp.hr_distance_ft,
               opk.opp_pitcher_bb_rate, opk.opp_pitcher_k_rate
        FROM batter_projections bp
        JOIN games g    ON g.id  = bp.game_id
        JOIN players p  ON p.id  = bp.player_id
        LEFT JOIN game_sim_batter_props sbp
               ON sbp.game_id = bp.game_id AND sbp.player_id = bp.player_id
        LEFT JOIN players op ON op.id = bp.opposing_pitcher_id
        JOIN teams t    ON t.id  = CASE WHEN bp.is_home THEN g.home_team_id ELSE g.away_team_id END
        JOIN teams ht   ON ht.id = g.home_team_id
        JOIN teams at2  ON at2.id = g.away_team_id
        LEFT JOIN stadiums s ON s.id = g.stadium_id
        LEFT JOIN batter_batted_ball bb
               ON bb.player_id = bp.player_id
              AND bb.season = EXTRACT(YEAR FROM g.game_date)::int
        -- Walk-card driver: the opposing starter's control, BF-weighted across handedness
        -- (filter season — pitcher_skill keeps multiple seasons at one key). Same pattern as
        -- the pitcher-prop query's `pk` lateral.
        LEFT JOIN LATERAL (
            SELECT SUM(ps.bb_rate * ps.batters_faced) / NULLIF(SUM(ps.batters_faced), 0) AS opp_pitcher_bb_rate,
                   SUM(ps.k_rate  * ps.batters_faced) / NULLIF(SUM(ps.batters_faced), 0) AS opp_pitcher_k_rate
            FROM pitcher_skill ps
            WHERE ps.player_id = bp.opposing_pitcher_id
              AND ps.season = EXTRACT(YEAR FROM g.game_date)::int
        ) opk ON TRUE
        WHERE g.game_date = ?
          AND %s
        """.formatted(GameStatus.livePredicate("g"));

    // How often the player has cleared each card's line recently and on the season
    // (0.5 occurrence lines for hr/bb; the 1.5 lines for total bases and H+R+RBI).
    // L10 spans seasons on purpose (recent form early in the year); season is the
    // current calendar year only. H+R+RBI aggregates additionally require runs/rbi
    // non-null: those columns are boxscore-only (V69) and older rows predate the
    // backfill — n_hrr_season keeps the blend's sample size honest for that market.
    private static final String RATES_SQL = """
        WITH logs AS (
            SELECT hits, home_runs, strikeouts, walks, total_bases, runs, rbi, game_date,
                   ROW_NUMBER() OVER (ORDER BY game_date DESC) AS rn
            FROM player_game_stats
            WHERE player_id = ? AND game_date < ? AND plate_appearances > 0
        )
        SELECT
            AVG((hits > 0)::int)        FILTER (WHERE rn <= 10) AS hit_l10,
            AVG((home_runs > 0)::int)   FILTER (WHERE rn <= 10) AS hr_l10,
            AVG((strikeouts > 0)::int)  FILTER (WHERE rn <= 10) AS k_l10,
            AVG((walks > 0)::int)       FILTER (WHERE rn <= 10) AS bb_l10,
            AVG((total_bases >= 2)::int) FILTER (WHERE rn <= 10) AS tb_l10,
            AVG(((hits + runs + rbi) >= 2)::int)
                FILTER (WHERE rn <= 10 AND runs IS NOT NULL AND rbi IS NOT NULL) AS hrr_l10,
            AVG((hits > 0)::int)        FILTER (WHERE game_date >= ?) AS hit_season,
            AVG((home_runs > 0)::int)   FILTER (WHERE game_date >= ?) AS hr_season,
            AVG((strikeouts > 0)::int)  FILTER (WHERE game_date >= ?) AS k_season,
            AVG((walks > 0)::int)       FILTER (WHERE game_date >= ?) AS bb_season,
            AVG((total_bases >= 2)::int) FILTER (WHERE game_date >= ?) AS tb_season,
            AVG(((hits + runs + rbi) >= 2)::int)
                FILTER (WHERE game_date >= ? AND runs IS NOT NULL AND rbi IS NOT NULL) AS hrr_season,
            COUNT(*)                    FILTER (WHERE game_date >= ?) AS n_season,
            COUNT(*) FILTER (WHERE game_date >= ? AND runs IS NOT NULL AND rbi IS NOT NULL)
                AS n_hrr_season
        FROM logs
        """;

    // Batched form of RATES_SQL: clear rates for many players in one round-trip. Same
    // window logic, but PARTITION BY player_id and GROUP BY player_id so a single query
    // replaces the per-candidate N+1. Player ids are passed as a SQL array (= ANY(?)).
    private static final String RATES_BATCH_SQL = """
        WITH logs AS (
            SELECT player_id, hits, home_runs, strikeouts, walks, total_bases, runs, rbi,
                   game_date,
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC) AS rn
            FROM player_game_stats
            WHERE player_id = ANY(?) AND game_date < ? AND plate_appearances > 0
        )
        SELECT
            player_id,
            AVG((hits > 0)::int)        FILTER (WHERE rn <= 10) AS hit_l10,
            AVG((home_runs > 0)::int)   FILTER (WHERE rn <= 10) AS hr_l10,
            AVG((strikeouts > 0)::int)  FILTER (WHERE rn <= 10) AS k_l10,
            AVG((walks > 0)::int)       FILTER (WHERE rn <= 10) AS bb_l10,
            AVG((total_bases >= 2)::int) FILTER (WHERE rn <= 10) AS tb_l10,
            AVG(((hits + runs + rbi) >= 2)::int)
                FILTER (WHERE rn <= 10 AND runs IS NOT NULL AND rbi IS NOT NULL) AS hrr_l10,
            AVG((hits > 0)::int)        FILTER (WHERE game_date >= ?) AS hit_season,
            AVG((home_runs > 0)::int)   FILTER (WHERE game_date >= ?) AS hr_season,
            AVG((strikeouts > 0)::int)  FILTER (WHERE game_date >= ?) AS k_season,
            AVG((walks > 0)::int)       FILTER (WHERE game_date >= ?) AS bb_season,
            AVG((total_bases >= 2)::int) FILTER (WHERE game_date >= ?) AS tb_season,
            AVG(((hits + runs + rbi) >= 2)::int)
                FILTER (WHERE game_date >= ? AND runs IS NOT NULL AND rbi IS NOT NULL) AS hrr_season,
            COUNT(*)                    FILTER (WHERE game_date >= ?) AS n_season,
            COUNT(*) FILTER (WHERE game_date >= ? AND runs IS NOT NULL AND rbi IS NOT NULL)
                AS n_hrr_season
        FROM logs
        GROUP BY player_id
        """;

    // Best cached over-price for the player's 0.5 line, if odds were ever pulled for
    // this slate. Absence is normal (model-only board).
    private static final String PRICE_SQL = """
        SELECT ppo.bookmaker, ppo.price_american, ppo.price_decimal
        FROM player_prop_odds ppo
        JOIN games g ON g.id = ppo.game_id
        WHERE g.game_date = ? AND ppo.player_id = ? AND ppo.market = ?
          AND ppo.side = 'over' AND ppo.line = 0.5
        ORDER BY ppo.price_decimal DESC
        LIMIT 1
        """;

    // Line-based batter markets (tb / hrr) quote real lines that vary by player, so the
    // 0.5-hard-wired PRICE_SQL can't serve them: consensus line (most-quoted across both
    // sides), then the best over-price at it — the batter analog of PITCHER_PRICE_SQL.
    private static final String BATTER_LINE_PRICE_SQL = """
        WITH quotes AS (
            SELECT ppo.line, ppo.side, ppo.bookmaker, ppo.price_american, ppo.price_decimal,
                   COUNT(*) OVER (PARTITION BY ppo.line) AS books_at_line
            FROM player_prop_odds ppo
            JOIN games g ON g.id = ppo.game_id
            WHERE g.game_date = ? AND ppo.player_id = ? AND ppo.market = ?
        )
        SELECT line, bookmaker, price_american, price_decimal
        FROM quotes
        WHERE side = 'over'
        ORDER BY books_at_line DESC, price_decimal DESC
        LIMIT 1
        """;

    // Starting-pitcher projections + workload distribution for the pitcher-prop cards.
    // p_k thresholds are 4.5/5.5/6.5; p_outs are 14.5/17.5 (fixed by the workload model).
    // hits-allowed / earned-runs come from the game simulator (game_sim_pitcher_props):
    // raw histogram counts the service turns into P(over line). opponent = the lineup
    // this starter faces.
    private static final String PITCHER_SQL = """
        SELECT pp.game_id, at2.abbreviation || ' @ ' || ht.abbreviation AS matchup,
               pp.pitcher_id, p.full_name, t.abbreviation AS team,
               opp.abbreviation AS opponent,
               pp.expected_k, pp.expected_outs, pp.expected_ip,
               (pp.workload->'p_k'->>'4.5')::float     AS pk_45,
               (pp.workload->'p_k'->>'5.5')::float     AS pk_55,
               (pp.workload->'p_k'->>'6.5')::float     AS pk_65,
               (pp.workload->'p_outs'->>'14.5')::float AS po_145,
               (pp.workload->'p_outs'->>'17.5')::float AS po_175,
               spp.n_sims AS spp_n_sims,
               spp.expected_hits AS spp_hits, spp.expected_er AS spp_er,
               spp.hits_hist, spp.er_hist,
               pk.pitcher_k_rate, pk.pitcher_bb_rate, pk.pitcher_xwoba_against, pk.pitcher_hr_per_pa,
               ol.opp_k_rate, ol.opp_xwoba,
               ars.arsenal_json
        FROM pitcher_projections pp
        JOIN games g   ON g.id  = pp.game_id
        JOIN players p ON p.id  = pp.pitcher_id
        JOIN teams t   ON t.id  = CASE WHEN pp.is_home THEN g.home_team_id ELSE g.away_team_id END
        JOIN teams opp ON opp.id = CASE WHEN pp.is_home THEN g.away_team_id ELSE g.home_team_id END
        JOIN teams ht  ON ht.id = g.home_team_id
        JOIN teams at2 ON at2.id = g.away_team_id
        LEFT JOIN game_sim_pitcher_props spp
               ON spp.game_id = pp.game_id AND spp.pitcher_id = pp.pitcher_id
        -- Reasoning drivers: the pitcher's own profile, BF-weighted across handedness
        -- (filter season — pitcher_skill keeps multiple seasons at one key).
        LEFT JOIN LATERAL (
            SELECT SUM(ps.k_rate       * ps.batters_faced) / NULLIF(SUM(ps.batters_faced), 0) AS pitcher_k_rate,
                   SUM(ps.bb_rate      * ps.batters_faced) / NULLIF(SUM(ps.batters_faced), 0) AS pitcher_bb_rate,
                   SUM(ps.xwoba_against* ps.batters_faced) / NULLIF(SUM(ps.batters_faced), 0) AS pitcher_xwoba_against,
                   SUM(ps.hr_per_pa    * ps.batters_faced) / NULLIF(SUM(ps.batters_faced), 0) AS pitcher_hr_per_pa
            FROM pitcher_skill ps
            WHERE ps.player_id = pp.pitcher_id
              AND ps.season = EXTRACT(YEAR FROM g.game_date)::int
        ) pk ON TRUE
        -- Reasoning driver: the pitcher's top pitches, aggregated across handedness over the
        -- latest snapshot on/before the game date (pitch-weighted usage / whiff / velocity).
        LEFT JOIN LATERAL (
            WITH snap AS (
                SELECT season, as_of_date FROM pitcher_arsenal
                WHERE player_id = pp.pitcher_id AND as_of_date <= g.game_date
                ORDER BY as_of_date DESC, season DESC LIMIT 1
            ),
            agg AS (
                SELECT a.pitch_type,
                       SUM(a.pitches_thrown) AS pitches,
                       SUM(a.usage_rate   * a.pitches_thrown) / NULLIF(SUM(a.pitches_thrown), 0) AS usage_rate,
                       SUM(a.whiff_rate   * a.pitches_thrown) / NULLIF(SUM(a.pitches_thrown), 0) AS whiff_rate,
                       SUM(a.avg_velocity * a.pitches_thrown) / NULLIF(SUM(a.pitches_thrown), 0) AS avg_velocity
                FROM pitcher_arsenal a
                JOIN snap ON snap.season = a.season AND snap.as_of_date = a.as_of_date
                WHERE a.player_id = pp.pitcher_id
                GROUP BY a.pitch_type
            )
            SELECT json_agg(json_build_object(
                       'pitchType', pitch_type, 'usageRate', usage_rate,
                       'whiffRate', whiff_rate, 'avgVelocity', avg_velocity)
                   ORDER BY pitches DESC) AS arsenal_json
            FROM (SELECT * FROM agg ORDER BY pitches DESC LIMIT 4) top
        ) ars ON TRUE
        -- Reasoning driver: the opposing lineup he faces — PA-weighted K rate and xwOBA
        -- over that team's projected batters for this game.
        LEFT JOIN LATERAL (
            SELECT SUM(bs.k_rate * bp2.expected_pa) / NULLIF(SUM(bp2.expected_pa), 0)
                       AS opp_k_rate,
                   SUM(bs.xwoba  * bp2.expected_pa) / NULLIF(SUM(bp2.expected_pa), 0)
                       AS opp_xwoba
            FROM batter_projections bp2
            JOIN batter_skill bs ON bs.player_id = bp2.player_id
            WHERE bp2.game_id = pp.game_id AND bp2.is_home <> pp.is_home
        ) ol ON TRUE
        WHERE g.game_date = ?
          AND %s
        """.formatted(GameStatus.livePredicate("g"));

    // De-vig inputs for one pitcher market across the whole slate (one query per market,
    // avoiding a per-pitcher-per-side N+1): each starter's consensus line (most-quoted
    // across both sides), the average implied probability per side at it (the no-vig
    // normalization inputs), and the best price per side at it (EV display).
    private static final String PITCHER_MARKET_QUOTES_SQL = """
        WITH quotes AS (
            SELECT ppo.game_id, ppo.player_id, ppo.side, ppo.line, ppo.bookmaker,
                   ppo.price_american, ppo.price_decimal, ppo.implied_prob,
                   COUNT(*) OVER (PARTITION BY ppo.game_id, ppo.player_id, ppo.line)
                       AS books_at_line
            FROM player_prop_odds ppo
            JOIN games g ON g.id = ppo.game_id
            WHERE g.game_date = ? AND ppo.market = ?
        ),
        consensus AS (
            SELECT DISTINCT ON (game_id, player_id) game_id, player_id, line
            FROM quotes
            ORDER BY game_id, player_id, books_at_line DESC, line
        )
        SELECT q.game_id, q.player_id, q.line,
               AVG(q.implied_prob) FILTER (WHERE q.side = 'over')  AS over_implied,
               AVG(q.implied_prob) FILTER (WHERE q.side = 'under') AS under_implied,
               (ARRAY_AGG(q.bookmaker ORDER BY q.price_decimal DESC)
                   FILTER (WHERE q.side = 'over'))[1]  AS over_book,
               (ARRAY_AGG(q.price_american ORDER BY q.price_decimal DESC)
                   FILTER (WHERE q.side = 'over'))[1]  AS over_american,
               MAX(q.price_decimal) FILTER (WHERE q.side = 'over')  AS over_decimal,
               (ARRAY_AGG(q.bookmaker ORDER BY q.price_decimal DESC)
                   FILTER (WHERE q.side = 'under'))[1] AS under_book,
               (ARRAY_AGG(q.price_american ORDER BY q.price_decimal DESC)
                   FILTER (WHERE q.side = 'under'))[1] AS under_american,
               MAX(q.price_decimal) FILTER (WHERE q.side = 'under') AS under_decimal
        FROM quotes q
        JOIN consensus c USING (game_id, player_id, line)
        GROUP BY q.game_id, q.player_id, q.line
        """;

    // Consensus line for a starter's prop on a given side: most-quoted line, best price
    // there. Side ('over'/'under') is parameterized so the board can price whichever side
    // the model recommends.
    private static final String PITCHER_PRICE_SQL = """
        WITH quotes AS (
            SELECT line, bookmaker, price_american, price_decimal,
                   COUNT(*) OVER (PARTITION BY line) AS books_at_line
            FROM player_prop_odds
            WHERE game_id = ? AND player_id = ? AND market = ? AND side = ?
        )
        SELECT line, bookmaker, price_american, price_decimal
        FROM quotes
        ORDER BY books_at_line DESC, price_decimal DESC
        LIMIT 1
        """;

    public List<SlateRow> findSlateRows(LocalDate date) {
        return jdbc.query(SLATE_SQL, this::mapSlate, date);
    }

    public ClearRates findClearRates(int playerId, LocalDate date) {
        LocalDate seasonStart = LocalDate.of(date.getYear(), 1, 1);
        return jdbc.query(RATES_SQL,
            rs -> rs.next() ? mapRates(rs) : null,
            playerId, date, seasonStart, seasonStart, seasonStart, seasonStart,
            seasonStart, seasonStart, seasonStart, seasonStart);
    }

    /** Clear rates for many players in one query (keyed by player_id). Players with no
     *  qualifying game log are simply absent from the map — same as a null single lookup. */
    public Map<Integer, ClearRates> findClearRatesBatch(Collection<Integer> playerIds, LocalDate date) {
        if (playerIds.isEmpty()) {
            return Map.of();
        }
        LocalDate seasonStart = LocalDate.of(date.getYear(), 1, 1);
        Integer[] ids = playerIds.toArray(new Integer[0]);
        return jdbc.query(
            con -> {
                PreparedStatement ps = con.prepareStatement(RATES_BATCH_SQL);
                ps.setArray(1, con.createArrayOf("integer", ids));
                ps.setObject(2, date);
                for (int i = 3; i <= 10; i++) {
                    ps.setObject(i, seasonStart);
                }
                return ps;
            },
            rs -> {
                Map<Integer, ClearRates> out = new HashMap<>();
                while (rs.next()) {
                    out.put(rs.getInt("player_id"), mapRates(rs));
                }
                return out;
            });
    }

    public BestPrice findBestOverPrice(LocalDate date, int playerId, String market) {
        List<BestPrice> rows = jdbc.query(PRICE_SQL,
            (rs, n) -> new BestPrice(
                rs.getString("bookmaker"),
                rs.getInt("price_american"),
                rs.getDouble("price_decimal")),
            date, playerId, market);
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** Consensus line + best over-price for a line-based batter market (tb/hrr);
     *  null when no odds. */
    public PitcherPrice findBatterLinePrice(LocalDate date, int playerId, String market) {
        List<PitcherPrice> rows = jdbc.query(BATTER_LINE_PRICE_SQL,
            (rs, n) -> new PitcherPrice(
                dbl(rs, "line"), rs.getString("bookmaker"),
                rs.getInt("price_american"), rs.getDouble("price_decimal")),
            date, playerId, market);
        return rows.isEmpty() ? null : rows.get(0);
    }

    public List<PitcherRow> findPitcherRows(LocalDate date) {
        return jdbc.query(PITCHER_SQL, (rs, n) -> new PitcherRow(
            rs.getLong("game_id"), rs.getString("matchup"),
            rs.getInt("pitcher_id"), rs.getString("full_name"),
            rs.getString("team"), rs.getString("opponent"),
            dbl(rs, "expected_k"), dbl(rs, "expected_outs"), dbl(rs, "expected_ip"),
            dbl(rs, "pk_45"), dbl(rs, "pk_55"), dbl(rs, "pk_65"),
            dbl(rs, "po_145"), dbl(rs, "po_175"),
            (Integer) rs.getObject("spp_n_sims"),
            dbl(rs, "spp_hits"), dbl(rs, "spp_er"),
            toIntArray(rs.getArray("hits_hist")), toIntArray(rs.getArray("er_hist")),
            dbl(rs, "pitcher_k_rate"), dbl(rs, "pitcher_bb_rate"),
            dbl(rs, "pitcher_xwoba_against"), dbl(rs, "pitcher_hr_per_pa"),
            dbl(rs, "opp_k_rate"), dbl(rs, "opp_xwoba"),
            parseArsenal(rs.getString("arsenal_json"))),
            date);
    }

    /** json_agg of the pitcher's top pitches → typed list; empty when null or unparseable. */
    private static List<PitcherPropPickDto.ArsenalPitch> parseArsenal(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            return ARSENAL_JSON.readValue(json, ARSENAL_TYPE);
        } catch (Exception e) {
            return List.of();
        }
    }

    /** Slate-wide de-vig inputs for one pitcher market, keyed by (game, pitcher).
     *  Pitchers with no quotes are simply absent. */
    public Map<PitcherQuoteKey, PitcherQuotes> findPitcherMarketQuotes(LocalDate date, String market) {
        return jdbc.query(PITCHER_MARKET_QUOTES_SQL, rs -> {
            Map<PitcherQuoteKey, PitcherQuotes> out = new HashMap<>();
            while (rs.next()) {
                double line = rs.getDouble("line");
                Double overDec = dbl(rs, "over_decimal");
                Double underDec = dbl(rs, "under_decimal");
                out.put(new PitcherQuoteKey(rs.getLong("game_id"), rs.getInt("player_id")),
                    new PitcherQuotes(line,
                        dbl(rs, "over_implied"), dbl(rs, "under_implied"),
                        overDec == null ? null : new PitcherPrice(line,
                            rs.getString("over_book"), rs.getInt("over_american"), overDec),
                        underDec == null ? null : new PitcherPrice(line,
                            rs.getString("under_book"), rs.getInt("under_american"), underDec)));
            }
            return out;
        }, date, market);
    }

    /** Consensus line + best price for a starter's prop on the given side; null when no odds. */
    public PitcherPrice findPitcherPrice(long gameId, int pitcherId, String market, String side) {
        List<PitcherPrice> rows = jdbc.query(PITCHER_PRICE_SQL,
            (rs, n) -> new PitcherPrice(
                dbl(rs, "line"), rs.getString("bookmaker"),
                rs.getInt("price_american"), rs.getDouble("price_decimal")),
            gameId, pitcherId, market, side);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private SlateRow mapSlate(ResultSet rs, int n) throws SQLException {
        return new SlateRow(
            rs.getLong("game_id"),
            rs.getString("matchup"),
            rs.getInt("player_id"),
            rs.getString("full_name"),
            rs.getString("team_abbr"),
            (Integer) rs.getObject("lineup_position"),
            (Boolean) rs.getObject("lineup_confirmed"),
            dbl(rs, "expected_pa"),
            dbl(rs, "p_hit_1plus"),
            dbl(rs, "p_hr"),
            dbl(rs, "p_k_1plus"),
            dbl(rs, "p_bb_1plus"),
            dbl(rs, "sim_hit"),
            dbl(rs, "sim_hr"),
            dbl(rs, "sim_k"),
            (Integer) rs.getObject("sim_n_sims"),
            dbl(rs, "sim_expected_tb"),
            dbl(rs, "sim_expected_hrr"),
            toIntArray(rs.getArray("tb_hist")),
            toIntArray(rs.getArray("hrr_hist")),
            dbl(rs, "adj_park"),
            dbl(rs, "adj_pitcher"),
            dbl(rs, "adj_weather_hr"),
            dbl(rs, "adj_weather_hits"),
            dbl(rs, "adj_defense"),
            dbl(rs, "matchup_xwoba"),
            rs.getString("matchup_quality"),
            rs.getString("pitcher_data_quality"),
            (Integer) rs.getObject("opposing_pitcher_id"),
            rs.getString("opposing_pitcher"),
            rs.getString("stadium"),
            rs.getString("bats"),
            dbl(rs, "lf_line_ft"),
            dbl(rs, "lf_wall_ft"),
            dbl(rs, "rf_line_ft"),
            dbl(rs, "rf_wall_ft"),
            dbl(rs, "pull_pct"),
            dbl(rs, "fb_pct"),
            dbl(rs, "avg_launch_speed"),
            dbl(rs, "hr_distance_ft"),
            dbl(rs, "opp_pitcher_bb_rate"),
            dbl(rs, "opp_pitcher_k_rate"));
    }

    private ClearRates mapRates(ResultSet rs) throws SQLException {
        return new ClearRates(
            dbl(rs, "hit_l10"), dbl(rs, "hr_l10"), dbl(rs, "k_l10"), dbl(rs, "bb_l10"),
            dbl(rs, "tb_l10"), dbl(rs, "hrr_l10"),
            dbl(rs, "hit_season"), dbl(rs, "hr_season"), dbl(rs, "k_season"), dbl(rs, "bb_season"),
            dbl(rs, "tb_season"), dbl(rs, "hrr_season"),
            rs.getInt("n_season"), rs.getInt("n_hrr_season"));
    }

    private static Double dbl(ResultSet rs, String col) throws SQLException {
        Object v = rs.getObject(col);
        return v == null ? null : ((Number) v).doubleValue();
    }

    /** Postgres INTEGER[] -> int[]; empty array when the column is NULL (no sim row). */
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

    public record SlateRow(
        long gameId, String matchup,
        int playerId, String player, String team,
        Integer lineupPosition, Boolean lineupConfirmed, Double expectedPa,
        Double pHit1, Double pHr, Double pK1, Double pBb1,
        // Monte-Carlo simulator's per-batter estimate of the same markets (null when the
        // sim didn't cover this batter — e.g. a padded league-average lineup slot).
        Double pSimHit, Double pSimHr, Double pSimK,
        // Simulator total-bases / hits+runs+RBI distributions (V69): raw count histograms
        // over simNSims sims, bins 0..N with a >=N catch-all. Empty when no sim row —
        // the tb/hrr cards are sim-native, so those batters simply can't carry them.
        Integer simNSims, Double simExpectedTb, Double simExpectedHrr,
        int[] tbHist, int[] hrrHist,
        Double adjPark, Double adjPitcher, Double adjWeatherHr, Double adjWeatherHits,
        Double adjDefense,
        Double matchupXwoba, String matchupQuality, String pitcherDataQuality,
        Integer opposingPitcherId, String opposingPitcher, String stadium,
        String bats,
        Double lfLineFt, Double lfWallFt, Double rfLineFt, Double rfWallFt,
        Double pullPct, Double fbPct, Double avgLaunchSpeed,
        // Projected HR carry (ft) in this game's park/weather — the long-ball-upside axis.
        Double hrDistanceFt,
        // Opposing starter's control, BF-weighted across handedness — the walk-card driver.
        // Null when the pitcher has no skill row (e.g. TBD starter).
        Double oppPitcherBbRate, Double oppPitcherKRate
    ) {}

    public record ClearRates(
        Double hitL10, Double hrL10, Double kL10, Double bbL10,
        Double tbL10, Double hrrL10,
        Double hitSeason, Double hrSeason, Double kSeason, Double bbSeason,
        Double tbSeason, Double hrrSeason,
        int nSeason,
        // H+R+RBI sample size: games with runs/rbi actually recorded (boxscore-only
        // columns, V69) — smaller than nSeason until the backfill catches history up.
        int nHrrSeason
    ) {}

    public record BestPrice(String bookmaker, int priceAmerican, double priceDecimal) {}

    public record PitcherRow(
        long gameId, String matchup,
        int pitcherId, String pitcher, String team, String opponent,
        Double expectedK, Double expectedOuts, Double expectedIp,
        Double pk45, Double pk55, Double pk65,
        Double po145, Double po175,
        // Game-simulator hits-allowed / earned-runs distributions (null when the game
        // had no sim row — e.g. no confirmed lineups). nSims is the histogram denominator.
        Integer nSims, Double expectedHits, Double expectedEr, int[] hitsHist, int[] erHist,
        // Reasoning drivers: the pitcher's own profile (BF-weighted K/BB/xwOBA-against/HR-PA)
        // and the opposing lineup's PA-weighted K rate / xwOBA. Null when skill rows are
        // absent. `arsenal` is the top pitches by usage (empty when no snapshot).
        Double pitcherKRate, Double pitcherBbRate, Double pitcherXwobaAgainst, Double pitcherHrPerPa,
        Double opponentKRate, Double opponentXwoba,
        List<PitcherPropPickDto.ArsenalPitch> arsenal
    ) {}

    /** Best cached over-price for a pitcher prop, with the line it sits on. */
    public record PitcherPrice(Double line, String bookmaker, int priceAmerican, double priceDecimal) {}

    /** Identity of one starter's quotes on a slate. */
    public record PitcherQuoteKey(long gameId, int pitcherId) {}

    /** One starter's de-vig inputs at his consensus line: average implied probability per
     *  side (either may be null when only one side is quoted — de-vigging then impossible)
     *  and the best price per side for EV display. */
    public record PitcherQuotes(
        double line,
        Double overImplied, Double underImplied,
        PitcherPrice bestOver, PitcherPrice bestUnder
    ) {}
}
