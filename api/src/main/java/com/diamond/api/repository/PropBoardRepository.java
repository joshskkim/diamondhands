package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;

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
               s.name AS stadium
        FROM batter_projections bp
        JOIN games g    ON g.id  = bp.game_id
        JOIN players p  ON p.id  = bp.player_id
        LEFT JOIN players op ON op.id = bp.opposing_pitcher_id
        JOIN teams t    ON t.id  = CASE WHEN bp.is_home THEN g.home_team_id ELSE g.away_team_id END
        JOIN teams ht   ON ht.id = g.home_team_id
        JOIN teams at2  ON at2.id = g.away_team_id
        LEFT JOIN stadiums s ON s.id = g.stadium_id
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

    public List<SlateRow> findSlateRows(LocalDate date) {
        return jdbc.query(SLATE_SQL, this::mapSlate, date);
    }

    public ClearRates findClearRates(int playerId, LocalDate date) {
        LocalDate seasonStart = LocalDate.of(date.getYear(), 1, 1);
        return jdbc.query(RATES_SQL,
            rs -> rs.next() ? mapRates(rs) : null,
            playerId, date, seasonStart, seasonStart, seasonStart, seasonStart);
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
            rs.getString("stadium"));
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
        Integer opposingPitcherId, String opposingPitcher, String stadium
    ) {}

    public record ClearRates(
        Double hitL10, Double hrL10, Double kL10,
        Double hitSeason, Double hrSeason, Double kSeason,
        int nSeason
    ) {}

    public record BestPrice(String bookmaker, int priceAmerican, double priceDecimal) {}
}
