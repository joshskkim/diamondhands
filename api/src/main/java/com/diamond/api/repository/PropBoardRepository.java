package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

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

    private final JdbcTemplate jdbc;

    public PropBoardRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // Every projected batter on the slate with the factors that explain the number.
    private static final String SLATE_SQL = """
        SELECT bp.game_id, at2.abbreviation || ' @ ' || ht.abbreviation AS matchup,
               bp.player_id, p.full_name, t.abbreviation AS team_abbr,
               bp.lineup_position, bp.lineup_confirmed, bp.expected_pa,
               bp.p_hit_1plus, bp.p_hr, bp.p_k_1plus,
               bp.adj_park, bp.adj_pitcher, bp.adj_weather_hr, bp.adj_weather_hits,
               bp.matchup_xwoba, bp.matchup_quality, bp.pitcher_data_quality,
               bp.opposing_pitcher_id, op.full_name AS opposing_pitcher,
               s.name AS stadium,
               COALESCE(p.bats, 'R') AS bats,
               s.lf_line_ft, s.lf_wall_ft, s.rf_line_ft, s.rf_wall_ft,
               bb.pull_pct, bb.fb_pct, bb.avg_launch_speed
        FROM batter_projections bp
        JOIN games g    ON g.id  = bp.game_id
        JOIN players p  ON p.id  = bp.player_id
        LEFT JOIN players op ON op.id = bp.opposing_pitcher_id
        JOIN teams t    ON t.id  = CASE WHEN bp.is_home THEN g.home_team_id ELSE g.away_team_id END
        JOIN teams ht   ON ht.id = g.home_team_id
        JOIN teams at2  ON at2.id = g.away_team_id
        LEFT JOIN stadiums s ON s.id = g.stadium_id
        LEFT JOIN batter_batted_ball bb
               ON bb.player_id = bp.player_id
              AND bb.season = EXTRACT(YEAR FROM g.game_date)::int
        WHERE g.game_date = ?
        """;

    // How often the player has cleared each 0.5 line recently and on the season.
    // L10 spans seasons on purpose (recent form early in the year); season is the
    // current calendar year only.
    private static final String RATES_SQL = """
        WITH logs AS (
            SELECT hits, home_runs, strikeouts, game_date,
                   ROW_NUMBER() OVER (ORDER BY game_date DESC) AS rn
            FROM player_game_stats
            WHERE player_id = ? AND game_date < ? AND plate_appearances > 0
        )
        SELECT
            AVG((hits > 0)::int)       FILTER (WHERE rn <= 10) AS hit_l10,
            AVG((home_runs > 0)::int)  FILTER (WHERE rn <= 10) AS hr_l10,
            AVG((strikeouts > 0)::int) FILTER (WHERE rn <= 10) AS k_l10,
            AVG((hits > 0)::int)       FILTER (WHERE game_date >= ?) AS hit_season,
            AVG((home_runs > 0)::int)  FILTER (WHERE game_date >= ?) AS hr_season,
            AVG((strikeouts > 0)::int) FILTER (WHERE game_date >= ?) AS k_season,
            COUNT(*)                   FILTER (WHERE game_date >= ?) AS n_season
        FROM logs
        """;

    // Batched form of RATES_SQL: clear rates for many players in one round-trip. Same
    // window logic, but PARTITION BY player_id and GROUP BY player_id so a single query
    // replaces the per-candidate N+1. Player ids are passed as a SQL array (= ANY(?)).
    private static final String RATES_BATCH_SQL = """
        WITH logs AS (
            SELECT player_id, hits, home_runs, strikeouts, game_date,
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC) AS rn
            FROM player_game_stats
            WHERE player_id = ANY(?) AND game_date < ? AND plate_appearances > 0
        )
        SELECT
            player_id,
            AVG((hits > 0)::int)       FILTER (WHERE rn <= 10) AS hit_l10,
            AVG((home_runs > 0)::int)  FILTER (WHERE rn <= 10) AS hr_l10,
            AVG((strikeouts > 0)::int) FILTER (WHERE rn <= 10) AS k_l10,
            AVG((hits > 0)::int)       FILTER (WHERE game_date >= ?) AS hit_season,
            AVG((home_runs > 0)::int)  FILTER (WHERE game_date >= ?) AS hr_season,
            AVG((strikeouts > 0)::int) FILTER (WHERE game_date >= ?) AS k_season,
            COUNT(*)                   FILTER (WHERE game_date >= ?) AS n_season
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

    // Starting-pitcher projections + workload distribution for the pitcher-prop cards.
    // p_k thresholds are 4.5/5.5/6.5; p_outs are 14.5/17.5 (fixed by the workload model).
    // opponent = the lineup this starter faces.
    private static final String PITCHER_SQL = """
        SELECT pp.game_id, at2.abbreviation || ' @ ' || ht.abbreviation AS matchup,
               pp.pitcher_id, p.full_name, t.abbreviation AS team,
               opp.abbreviation AS opponent,
               pp.expected_k, pp.expected_outs, pp.expected_ip,
               (pp.workload->'p_k'->>'4.5')::float     AS pk_45,
               (pp.workload->'p_k'->>'5.5')::float     AS pk_55,
               (pp.workload->'p_k'->>'6.5')::float     AS pk_65,
               (pp.workload->'p_outs'->>'14.5')::float AS po_145,
               (pp.workload->'p_outs'->>'17.5')::float AS po_175
        FROM pitcher_projections pp
        JOIN games g   ON g.id  = pp.game_id
        JOIN players p ON p.id  = pp.pitcher_id
        JOIN teams t   ON t.id  = CASE WHEN pp.is_home THEN g.home_team_id ELSE g.away_team_id END
        JOIN teams opp ON opp.id = CASE WHEN pp.is_home THEN g.away_team_id ELSE g.home_team_id END
        JOIN teams ht  ON ht.id = g.home_team_id
        JOIN teams at2 ON at2.id = g.away_team_id
        WHERE g.game_date = ?
        """;

    // Consensus over-line for a starter's prop: most-quoted line, best over price there.
    private static final String PITCHER_PRICE_SQL = """
        WITH quotes AS (
            SELECT line, bookmaker, price_american, price_decimal,
                   COUNT(*) OVER (PARTITION BY line) AS books_at_line
            FROM player_prop_odds
            WHERE game_id = ? AND player_id = ? AND market = ? AND side = 'over'
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
            playerId, date, seasonStart, seasonStart, seasonStart, seasonStart);
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
                ps.setObject(3, seasonStart);
                ps.setObject(4, seasonStart);
                ps.setObject(5, seasonStart);
                ps.setObject(6, seasonStart);
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

    public List<PitcherRow> findPitcherRows(LocalDate date) {
        return jdbc.query(PITCHER_SQL, (rs, n) -> new PitcherRow(
            rs.getLong("game_id"), rs.getString("matchup"),
            rs.getInt("pitcher_id"), rs.getString("full_name"),
            rs.getString("team"), rs.getString("opponent"),
            dbl(rs, "expected_k"), dbl(rs, "expected_outs"), dbl(rs, "expected_ip"),
            dbl(rs, "pk_45"), dbl(rs, "pk_55"), dbl(rs, "pk_65"),
            dbl(rs, "po_145"), dbl(rs, "po_175")),
            date);
    }

    /** Consensus over-line + best price for a starter's prop; null when no odds. */
    public PitcherPrice findPitcherOverPrice(long gameId, int pitcherId, String market) {
        List<PitcherPrice> rows = jdbc.query(PITCHER_PRICE_SQL,
            (rs, n) -> new PitcherPrice(
                dbl(rs, "line"), rs.getString("bookmaker"),
                rs.getInt("price_american"), rs.getDouble("price_decimal")),
            gameId, pitcherId, market);
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
            dbl(rs, "adj_park"),
            dbl(rs, "adj_pitcher"),
            dbl(rs, "adj_weather_hr"),
            dbl(rs, "adj_weather_hits"),
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
            dbl(rs, "avg_launch_speed"));
    }

    private ClearRates mapRates(ResultSet rs) throws SQLException {
        return new ClearRates(
            dbl(rs, "hit_l10"), dbl(rs, "hr_l10"), dbl(rs, "k_l10"),
            dbl(rs, "hit_season"), dbl(rs, "hr_season"), dbl(rs, "k_season"),
            rs.getInt("n_season"));
    }

    private static Double dbl(ResultSet rs, String col) throws SQLException {
        Object v = rs.getObject(col);
        return v == null ? null : ((Number) v).doubleValue();
    }

    public record SlateRow(
        long gameId, String matchup,
        int playerId, String player, String team,
        Integer lineupPosition, Boolean lineupConfirmed, Double expectedPa,
        Double pHit1, Double pHr, Double pK1,
        Double adjPark, Double adjPitcher, Double adjWeatherHr, Double adjWeatherHits,
        Double matchupXwoba, String matchupQuality, String pitcherDataQuality,
        Integer opposingPitcherId, String opposingPitcher, String stadium,
        String bats,
        Double lfLineFt, Double lfWallFt, Double rfLineFt, Double rfWallFt,
        Double pullPct, Double fbPct, Double avgLaunchSpeed
    ) {}

    public record ClearRates(
        Double hitL10, Double hrL10, Double kL10,
        Double hitSeason, Double hrSeason, Double kSeason,
        int nSeason
    ) {}

    public record BestPrice(String bookmaker, int priceAmerican, double priceDecimal) {}

    public record PitcherRow(
        long gameId, String matchup,
        int pitcherId, String pitcher, String team, String opponent,
        Double expectedK, Double expectedOuts, Double expectedIp,
        Double pk45, Double pk55, Double pk65,
        Double po145, Double po175
    ) {}

    /** Best cached over-price for a pitcher prop, with the line it sits on. */
    public record PitcherPrice(Double line, String bookmaker, int priceAmerican, double priceDecimal) {}
}
