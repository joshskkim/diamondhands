package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.sql.Types;
import java.time.LocalDate;

/**
 * Persistence for the agent: the run header + per-decision trajectory ({@code agent_runs} /
 * {@code agent_steps}, the eval Layer-2 source of truth) and the user-owned write targets
 * ({@code agent_recommendations}, {@code user_bets}, {@code line_alerts}). Recommendations and
 * bets carry the same selection-identity + grade columns as {@code model_picks}, so the
 * ingester's score-picks grader/CLV code grades them unchanged.
 */
@Repository
public class AgentRepository {

    private final JdbcTemplate jdbc;

    public AgentRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // ── trajectory ───────────────────────────────────────────────────────────────

    public long createRun(String channel, Long userId, String question, String model) {
        KeyHolder kh = new GeneratedKeyHolder();
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(
                "INSERT INTO agent_runs (channel, user_id, question, model, status) "
                + "VALUES (?,?,?,?, 'running')",
                new String[] {"id"});
            ps.setString(1, channel);
            if (userId == null) {
                ps.setNull(2, Types.BIGINT);
            } else {
                ps.setLong(2, userId);
            }
            ps.setString(3, question);
            ps.setString(4, model);
            return ps;
        }, kh);
        return kh.getKey().longValue();
    }

    public void addStep(long runId, int stepNo, String role, String toolName,
                        String argsJson, String resultSummary, Long latencyMs) {
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(
                "INSERT INTO agent_steps (run_id, step_no, role, tool_name, args_json, "
                + "result_summary, latency_ms) VALUES (?,?,?,?,?::jsonb,?,?)");
            ps.setLong(1, runId);
            ps.setInt(2, stepNo);
            ps.setString(3, role);
            ps.setString(4, toolName);
            ps.setString(5, argsJson);
            ps.setString(6, resultSummary);
            if (latencyMs == null) {
                ps.setNull(7, Types.INTEGER);
            } else {
                ps.setLong(7, latencyMs);
            }
            return ps;
        });
    }

    public void finishRun(long runId, String finalAnswer, String status, int toolCalls) {
        jdbc.update(
            "UPDATE agent_runs SET final_answer=?, status=?, tool_calls=?, finished_at=now() WHERE id=?",
            finalAnswer, status, toolCalls, runId);
    }

    // ── write targets ────────────────────────────────────────────────────────────

    public long insertRecommendation(Long runId, Long userId, LocalDate slate, long gameId,
                                     String market, String side, Double line, Integer playerId,
                                     String playerName, Double modelProb, Double fairProb, Double edge,
                                     Double evPct, Integer priceAmerican, String book, Double stakeUnits,
                                     Double confidence) {
        KeyHolder kh = new GeneratedKeyHolder();
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(
                """
                INSERT INTO agent_recommendations
                    (run_id, user_id, slate_date, game_id, market, side, line, player_id,
                     player_name, model_prob, fair_prob, edge, ev_pct, price_american, book,
                     stake_units, confidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                new String[] {"id"});
            setNullableLong(ps, 1, runId);
            setNullableLong(ps, 2, userId);
            ps.setObject(3, slate);
            ps.setLong(4, gameId);
            ps.setString(5, market);
            ps.setString(6, side);
            setNullableDouble(ps, 7, line);
            setNullableInt(ps, 8, playerId);
            ps.setString(9, playerName);
            setNullableDouble(ps, 10, modelProb);
            setNullableDouble(ps, 11, fairProb);
            setNullableDouble(ps, 12, edge);
            setNullableDouble(ps, 13, evPct);
            setNullableInt(ps, 14, priceAmerican);
            ps.setString(15, book);
            setNullableDouble(ps, 16, stakeUnits);
            setNullableDouble(ps, 17, confidence);
            return ps;
        }, kh);
        return kh.getKey().longValue();
    }

    /** Idempotent per selection per user per slate (user_bets_identity). Returns rows affected. */
    public int upsertUserBet(long userId, LocalDate slate, long gameId, String market, String side,
                             Double line, Integer playerId, String playerName, Double stakeUnits,
                             Integer priceAmerican, String book) {
        return jdbc.update(
            """
            INSERT INTO user_bets
                (user_id, slate_date, game_id, market, side, line, player_id, player_name,
                 stake_units, price_american, book)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (user_id, slate_date, game_id, market, side, player_id)
            DO UPDATE SET stake_units = EXCLUDED.stake_units,
                          price_american = EXCLUDED.price_american,
                          book = EXCLUDED.book,
                          placed_at = now()
            """,
            userId, slate, gameId, market, side, line, playerId, playerName,
            stakeUnits, priceAmerican, book);
    }

    public long insertLineAlert(long userId, LocalDate slate, Long gameId, String market, String side,
                                Double line, Integer playerId, Integer targetPriceAmerican,
                                Double targetEdge) {
        KeyHolder kh = new GeneratedKeyHolder();
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(
                """
                INSERT INTO line_alerts
                    (user_id, slate_date, game_id, market, side, line, player_id,
                     target_price_american, target_edge)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                new String[] {"id"});
            ps.setLong(1, userId);
            ps.setObject(2, slate);
            setNullableLong(ps, 3, gameId);
            ps.setString(4, market);
            ps.setString(5, side);
            setNullableDouble(ps, 6, line);
            setNullableInt(ps, 7, playerId);
            setNullableInt(ps, 8, targetPriceAmerican);
            setNullableDouble(ps, 9, targetEdge);
            return ps;
        }, kh);
        return kh.getKey().longValue();
    }

    private static void setNullableLong(PreparedStatement ps, int i, Long v) throws java.sql.SQLException {
        if (v == null) ps.setNull(i, Types.BIGINT); else ps.setLong(i, v);
    }

    private static void setNullableInt(PreparedStatement ps, int i, Integer v) throws java.sql.SQLException {
        if (v == null) ps.setNull(i, Types.INTEGER); else ps.setInt(i, v);
    }

    private static void setNullableDouble(PreparedStatement ps, int i, Double v) throws java.sql.SQLException {
        if (v == null) ps.setNull(i, Types.NUMERIC); else ps.setDouble(i, v);
    }
}
