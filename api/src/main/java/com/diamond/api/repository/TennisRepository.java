package com.diamond.api.repository;

import com.diamond.api.dto.*;
import com.diamond.api.service.TennisEv;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.TreeMap;

@Repository
public class TennisRepository {

    private final JdbcTemplate jdbc;

    public TennisRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // ── Slate board ──────────────────────────────────────────────────────────

    // Best (highest-decimal) quote per side via DISTINCT ON, joined onto each match.
    private static final String SCHEDULED_SQL = """
        WITH best AS (
            SELECT DISTINCT ON (match_id, side)
                   match_id, side, bookmaker, price_american, price_decimal, implied_prob
            FROM tennis_match_odds
            ORDER BY match_id, side, price_decimal DESC
        )
        SELECT m.id AS match_id, m.start_time_utc, m.surface, m.best_of, m.status,
               pa.id AS a_id, pa.full_name AS a_name, pa.country AS a_country,
               pb.id AS b_id, pb.full_name AS b_name, pb.country AS b_country,
               tp.p_win_a, tp.exp_total_games,
               ba.bookmaker AS a_book, ba.price_american AS a_am,
               ba.price_decimal AS a_dec, ba.implied_prob AS a_imp,
               bb.bookmaker AS b_book, bb.price_american AS b_am,
               bb.price_decimal AS b_dec, bb.implied_prob AS b_imp
        FROM tennis_matches m
        JOIN tennis_players pa ON pa.id = m.player_a_id
        JOIN tennis_players pb ON pb.id = m.player_b_id
        LEFT JOIN tennis_match_projections tp ON tp.match_id = m.id
        LEFT JOIN best ba ON ba.match_id = m.id AND ba.side = 'player_a'
        LEFT JOIN best bb ON bb.match_id = m.id AND bb.side = 'player_b'
        WHERE m.status = 'scheduled'
        ORDER BY m.start_time_utc NULLS LAST, m.id
        """;

    public List<TennisMatchDto> findScheduledMatches() {
        return jdbc.query(SCHEDULED_SQL, this::mapMatch);
    }

    private TennisMatchDto mapMatch(ResultSet rs, int rowNum) throws SQLException {
        TennisPlayerDto a = new TennisPlayerDto(rs.getString("a_id"), rs.getString("a_name"), rs.getString("a_country"));
        TennisPlayerDto b = new TennisPlayerDto(rs.getString("b_id"), rs.getString("b_name"), rs.getString("b_country"));
        Double pWinA = nd(rs, "p_win_a");
        TennisEvDto best = TennisEv.bestPlay(
            pWinA,
            ni(rs, "a_am"), nd(rs, "a_dec"), nd(rs, "a_imp"), rs.getString("a_book"), rs.getString("a_name"),
            ni(rs, "b_am"), nd(rs, "b_dec"), nd(rs, "b_imp"), rs.getString("b_book"), rs.getString("b_name"));
        return new TennisMatchDto(
            rs.getLong("match_id"), rs.getString("start_time_utc"),
            rs.getString("surface"), ni(rs, "best_of"), a, b,
            pWinA, nd(rs, "exp_total_games"), best, rs.getString("status"));
    }

    // ── Match detail ─────────────────────────────────────────────────────────

    private static final String DETAIL_SQL = """
        SELECT m.id AS match_id, m.start_time_utc, m.surface, m.best_of, m.status,
               pa.id AS a_id, pa.full_name AS a_name, pa.country AS a_country,
               pb.id AS b_id, pb.full_name AS b_name, pb.country AS b_country,
               tp.p_win_a, tp.p_serve_a, tp.p_serve_b, tp.exp_total_games, tp.prob_straight_sets,
               (tp.reasoning->>'elo_a')::numeric AS elo_a,
               (tp.reasoning->>'elo_b')::numeric AS elo_b
        FROM tennis_matches m
        JOIN tennis_players pa ON pa.id = m.player_a_id
        JOIN tennis_players pb ON pb.id = m.player_b_id
        LEFT JOIN tennis_match_projections tp ON tp.match_id = m.id
        WHERE m.id = ?
        """;

    private static final String QUOTES_SQL = """
        SELECT side, bookmaker, price_american, price_decimal, implied_prob
        FROM tennis_match_odds WHERE match_id = ?
        ORDER BY side, price_decimal DESC
        """;

    public TennisMatchDetailDto findMatchDetail(long matchId) {
        List<TennisQuoteDto> quotes = jdbc.query(QUOTES_SQL,
            (rs, n) -> new TennisQuoteDto(rs.getString("side"), rs.getString("bookmaker"),
                ni(rs, "price_american"), nd(rs, "price_decimal"), nd(rs, "implied_prob")),
            matchId);
        TennisTotalEvDto bestTotal = bestTotalPlay(matchId);
        List<TennisMatchDetailDto> rows = jdbc.query(DETAIL_SQL,
            (rs, n) -> mapDetail(rs, quotes, bestTotal), matchId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    // Best (highest-decimal) over/under per line, then the best +edge play across lines.
    private record TotalSide(Integer am, Double dec, Double imp, Double model, String book) {}

    private static final String TOTALS_SQL = """
        SELECT side, line, bookmaker, price_american, price_decimal, implied_prob, model_prob
        FROM tennis_total_odds WHERE match_id = ?
        ORDER BY line, side, price_decimal DESC
        """;

    private TennisTotalEvDto bestTotalPlay(long matchId) {
        TreeMap<Double, TotalSide> over = new TreeMap<>();
        TreeMap<Double, TotalSide> under = new TreeMap<>();
        jdbc.query(TOTALS_SQL, rs -> {
            double line = rs.getDouble("line");
            // rows are best-price-first per (line, side); keep the first seen
            TreeMap<Double, TotalSide> tgt = "over".equals(rs.getString("side")) ? over : under;
            tgt.putIfAbsent(line, new TotalSide(ni(rs, "price_american"), nd(rs, "price_decimal"),
                nd(rs, "implied_prob"), nd(rs, "model_prob"), rs.getString("bookmaker")));
        }, matchId);

        TennisTotalEvDto best = null;
        for (var e : over.entrySet()) {
            TotalSide o = e.getValue();
            TotalSide u = under.get(e.getKey());
            if (u == null) continue;
            TennisTotalEvDto cand = TennisEv.bestTotal(e.getKey(), o.model(),
                o.am(), o.dec(), o.imp(), o.book(), u.am(), u.dec(), u.imp(), u.book());
            if (cand != null && (best == null || cand.evPct() > best.evPct())) {
                best = cand;
            }
        }
        return best;
    }

    private TennisMatchDetailDto mapDetail(ResultSet rs, List<TennisQuoteDto> quotes,
                                           TennisTotalEvDto bestTotal) throws SQLException {
        TennisPlayerDto a = new TennisPlayerDto(rs.getString("a_id"), rs.getString("a_name"), rs.getString("a_country"));
        TennisPlayerDto b = new TennisPlayerDto(rs.getString("b_id"), rs.getString("b_name"), rs.getString("b_country"));
        Double pWinA = nd(rs, "p_win_a");

        // Best quote per side from the (already best-first ordered) quotes list.
        TennisQuoteDto qa = quotes.stream().filter(q -> q.side().equals("player_a")).findFirst().orElse(null);
        TennisQuoteDto qb = quotes.stream().filter(q -> q.side().equals("player_b")).findFirst().orElse(null);
        TennisEvDto best = TennisEv.bestPlay(
            pWinA,
            qa != null ? qa.priceAmerican() : null, qa != null ? qa.priceDecimal() : null,
            qa != null ? qa.impliedProb() : null, qa != null ? qa.bookmaker() : null, a.name(),
            qb != null ? qb.priceAmerican() : null, qb != null ? qb.priceDecimal() : null,
            qb != null ? qb.impliedProb() : null, qb != null ? qb.bookmaker() : null, b.name());

        return new TennisMatchDetailDto(
            rs.getLong("match_id"), rs.getString("start_time_utc"), rs.getString("surface"),
            ni(rs, "best_of"), rs.getString("status"), a, b,
            nd(rs, "elo_a"), nd(rs, "elo_b"), pWinA, nd(rs, "p_serve_a"), nd(rs, "p_serve_b"),
            nd(rs, "exp_total_games"), nd(rs, "prob_straight_sets"), quotes, best, bestTotal);
    }

    // ── Rankings ─────────────────────────────────────────────────────────────

    private static final String RANKINGS_SQL = """
        SELECT p.id, p.full_name, p.country, r.elo, r.serve_skill, r.return_skill, r.matches_count
        FROM tennis_player_ratings r
        JOIN tennis_players p ON p.id = r.player_id
        WHERE r.as_of_date = (SELECT max(as_of_date) FROM tennis_player_ratings)
          AND r.surface = ? AND r.matches_count >= ?
        ORDER BY r.elo DESC NULLS LAST
        LIMIT ?
        """;

    public List<TennisRankingDto> findRankings(String surface, int minMatches, int limit) {
        List<TennisRankingDto> out = new ArrayList<>();
        jdbc.query(RANKINGS_SQL, rs -> {
            TennisPlayerDto p = new TennisPlayerDto(rs.getString("id"), rs.getString("full_name"), rs.getString("country"));
            out.add(new TennisRankingDto(out.size() + 1, p, nd(rs, "elo"),
                nd(rs, "serve_skill"), nd(rs, "return_skill"), ni(rs, "matches_count")));
        }, surface, minMatches, limit);
        return out;
    }

    // ── Accuracy ─────────────────────────────────────────────────────────────

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static final String ACCURACY_SQL = """
        SELECT period_date, model_version, n, brier, baseline_brier, ece,
               calibration_buckets::text AS buckets
        FROM tennis_daily_accuracy
        WHERE surface = ? AND market = 'match_winner'
          AND model_version = (SELECT max(model_version) FROM tennis_daily_accuracy)
        ORDER BY period_date
        """;

    public TennisAccuracyDto findAccuracy(String surface) {
        List<TennisAccuracyDto.Point> series = new ArrayList<>();
        // Merge calibration deciles across months: lo -> [sumN, sumN*predMean, sumN*actRate, hi].
        TreeMap<Double, double[]> merged = new TreeMap<>();
        String[] modelVersion = {null};

        jdbc.query(ACCURACY_SQL, rs -> {
            modelVersion[0] = rs.getString("model_version");
            series.add(new TennisAccuracyDto.Point(
                rs.getString("period_date"), rs.getInt("n"),
                nd(rs, "brier"), nd(rs, "baseline_brier"), nd(rs, "ece")));
            mergeBuckets(merged, rs.getString("buckets"));
        }, surface);

        List<TennisAccuracyDto.CalibrationBucket> calibration = new ArrayList<>();
        for (var e : merged.entrySet()) {
            double[] v = e.getValue();
            int n = (int) v[0];
            if (n > 0) {
                calibration.add(new TennisAccuracyDto.CalibrationBucket(
                    e.getKey(), v[3], n, round(v[1] / n), round(v[2] / n)));
            }
        }
        return new TennisAccuracyDto(modelVersion[0], surface, series, calibration);
    }

    private static void mergeBuckets(TreeMap<Double, double[]> merged, String json) {
        if (json == null) return;
        try {
            for (JsonNode b : MAPPER.readTree(json)) {
                double lo = b.get("lo").asDouble();
                int n = b.get("n").asInt();
                double[] acc = merged.computeIfAbsent(lo, k -> new double[]{0, 0, 0, b.get("hi").asDouble()});
                acc[0] += n;
                acc[1] += n * b.get("predictedMean").asDouble();
                acc[2] += n * b.get("actualRate").asDouble();
            }
        } catch (Exception ignored) {
            // malformed buckets — skip this row's calibration contribution
        }
    }

    private static double round(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }

    // ── helpers ──────────────────────────────────────────────────────────────

    private static Integer ni(ResultSet rs, String col) throws SQLException {
        int v = rs.getInt(col);
        return rs.wasNull() ? null : v;
    }

    private static Double nd(ResultSet rs, String col) throws SQLException {
        BigDecimal v = rs.getBigDecimal(col);
        return v == null ? null : v.doubleValue();
    }
}
