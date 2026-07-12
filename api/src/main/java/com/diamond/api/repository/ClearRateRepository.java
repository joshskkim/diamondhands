package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

/**
 * A batter's demonstrated clear rate per prop market — the empirical target the model's
 * probability is regressed toward (see {@code PropBlend}).
 *
 * <p>Each rate is measured at ONE fixed line, and the SQL below is the definition of
 * record: hit/hr/k/bb are 1+ occurrence rates, tb and hrr are "&gt;= 2" (i.e. over 1.5).
 * A rate is therefore only comparable to a model probability priced at that same line —
 * blending a P(over 2.5 TB) toward the "&gt;= 2 TB" rate would blend toward a different
 * event. {@code PropBlend} enforces that.
 *
 * <p>There are deliberately no pitcher clear rates: the prop board edge-ranks pitcher
 * props on the raw model probability instead.
 */
@Repository
public class ClearRateRepository {

    // How often the player has cleared each market's line recently and on the season
    // (0.5 occurrence lines for hit/hr/k/bb; the 1.5 lines for total bases and H+R+RBI).
    // L10 spans seasons on purpose (recent form early in the year); season is the
    // current calendar year only. H+R+RBI aggregates additionally require runs/rbi
    // non-null: those columns are boxscore-only (V69) and older rows predate the
    // backfill — n_hrr_season keeps the blend's sample size honest for that market.
    // rn tiebreaks on game_id: without it a doubleheader at the L10 boundary ranks
    // nondeterministically, and the single/batch forms can disagree on which game
    // falls inside the window (caught live by RepositoryBatchEquivalenceTest).
    private static final String RATES_SQL = """
        WITH logs AS (
            SELECT hits, home_runs, strikeouts, walks, total_bases, runs, rbi, game_date,
                   ROW_NUMBER() OVER (ORDER BY game_date DESC, game_id DESC) AS rn
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
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC, game_id DESC) AS rn
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

    private final JdbcTemplate jdbc;

    public ClearRateRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
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
}
