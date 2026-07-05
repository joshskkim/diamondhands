package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * Candidate rows for the "Lotto of the Day" HR boom pick: every bottom-of-order batter on the
 * slate, joined to their season power/recent-form skill ({@code batter_skill}, keyed by player
 * regardless of season label) and the best HR-over-0.5 price across books (a LEFT JOIN — a
 * candidate with no posted price is still scorable, the pick just stands on the model).
 *
 * <p>{@link com.diamond.api.service.LottoService} applies the boom screen + score; this only
 * pulls the raw signals. Nothing here reads birth date / age — the pick is age-blind by design.
 */
@Repository
public class LottoRepository {

    /** Only the bottom third of the order (a confirmed lineup slot is required). */
    static final int BOTTOM_ORDER_MIN = 6;

    private final JdbcTemplate jdbc;

    public LottoRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final String CANDIDATES_SQL = """
        SELECT
            bp.player_id,
            p.full_name        AS player_name,
            p.bats,
            bp.is_home,
            bp.game_id,
            bp.lineup_position,
            bp.p_hr,
            bp.hr_distance_ft,
            bp.adj_park,
            bp.adj_pitcher,
            bp.adj_weather_hr,
            pit.full_name      AS pitcher_name,
            ht.abbreviation    AS home_abbr,
            at2.abbreviation   AS away_abbr,
            bs.iso,
            bs.iso_l30,
            bs.xwoba,
            bs.xwoba_l30,
            bb.barrel_pct      AS barrel_rate,
            bs.pa_l30,
            ho.price_american,
            ho.price_decimal,
            ho.bookmaker
        FROM batter_projections bp
        JOIN players p   ON p.id   = bp.player_id
        JOIN players pit ON pit.id = bp.opposing_pitcher_id
        JOIN games g     ON g.id   = bp.game_id
        JOIN teams ht    ON ht.id  = g.home_team_id
        JOIN teams at2   ON at2.id = g.away_team_id
        JOIN batter_skill bs ON bs.player_id = bp.player_id
        -- barrel rate lives in batter_batted_ball (barrel_pct), season-scoped; batter_skill's
        -- barrel_rate column is unpopulated. Season filter avoids the multi-season fan-out.
        JOIN batter_batted_ball bb
              ON bb.player_id = bp.player_id
             AND bb.season = EXTRACT(YEAR FROM g.game_date)::int
        LEFT JOIN LATERAL (
            SELECT po.price_american, po.price_decimal, po.bookmaker
            FROM player_prop_odds po
            WHERE po.game_id = bp.game_id AND po.player_id = bp.player_id
              AND po.market = 'hr' AND po.side = 'over' AND po.line = 0.5
            ORDER BY po.price_decimal DESC
            LIMIT 1
        ) ho ON true
        WHERE g.game_date = ?
          AND bp.lineup_position IS NOT NULL
          AND bp.lineup_position >= %d
          AND bp.p_hr IS NOT NULL
          AND bp.adj_park IS NOT NULL
          AND bp.adj_pitcher IS NOT NULL
          AND bp.adj_weather_hr IS NOT NULL
          AND bb.barrel_pct IS NOT NULL
          AND bs.iso IS NOT NULL
          AND bs.xwoba IS NOT NULL
          AND bs.xwoba_l30 IS NOT NULL
        """.formatted(BOTTOM_ORDER_MIN);

    public List<CandidateRow> findCandidates(LocalDate date) {
        return jdbc.query(CANDIDATES_SQL, (rs, n) -> new CandidateRow(
                rs.getLong("game_id"),
                rs.getInt("player_id"),
                rs.getString("player_name"),
                rs.getString("bats"),
                rs.getBoolean("is_home"),
                rs.getInt("lineup_position"),
                rs.getString("pitcher_name"),
                rs.getString("home_abbr"),
                rs.getString("away_abbr"),
                rs.getBigDecimal("p_hr").doubleValue(),
                rs.getBigDecimal("barrel_rate").doubleValue(),
                rs.getBigDecimal("iso").doubleValue(),
                toDouble(rs.getBigDecimal("iso_l30")),
                rs.getBigDecimal("xwoba").doubleValue(),
                rs.getBigDecimal("xwoba_l30").doubleValue(),
                rs.getObject("pa_l30", Integer.class),
                rs.getBigDecimal("adj_park").doubleValue(),
                rs.getBigDecimal("adj_pitcher").doubleValue(),
                rs.getBigDecimal("adj_weather_hr").doubleValue(),
                toDouble(rs.getBigDecimal("hr_distance_ft")),
                rs.getObject("price_american", Integer.class),
                toDouble(rs.getBigDecimal("price_decimal")),
                rs.getString("bookmaker")),
            date);
    }

    private static Double toDouble(BigDecimal bd) {
        return bd == null ? null : bd.doubleValue();
    }

    public record CandidateRow(
        long gameId, int playerId, String playerName, String bats, boolean isHome,
        int lineupPosition, String opposingPitcher, String homeAbbr, String awayAbbr,
        double pHr, double barrelRate, double isoSeason, Double isoL30,
        double xwoba, double xwobaL30, Integer paL30,
        double adjPark, double adjPitcher, double adjWeatherHr, Double hrDistanceFt,
        Integer priceAmerican, Double priceDecimal, String bestBook) {}
}
