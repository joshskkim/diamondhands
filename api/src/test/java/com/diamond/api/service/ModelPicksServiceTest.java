package com.diamond.api.service;

import com.diamond.api.dto.ReconcileRequest.PickKey;
import com.diamond.api.repository.ModelPicksRepository.ReconcileRow;
import com.diamond.api.service.ModelPicksService.ReconcileOp;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Locks the live-board reconcile decision (bump displaced / re-promote returned), mirroring the
 * ingester's plan_reconcile cases in ingester/tests/test_picks.py — minus insert, which the cron
 * owns. {@link ModelPicksService#planReconcile} is the pure core the endpoint applies.
 */
class ModelPicksServiceTest {

    private static final Instant NOW = Instant.parse("2026-06-25T18:00:00Z");
    private static final Instant UPCOMING = Instant.parse("2026-06-25T23:05:00Z");
    private static final Instant STARTED = Instant.parse("2026-06-25T17:00:00Z");

    private static PickKey key(long gameId, String market, String side, Integer playerId) {
        return new PickKey(gameId, market, side, playerId);
    }

    private static ReconcileRow row(long id, PickKey k, boolean active, boolean bumped, Instant start) {
        return new ReconcileRow(id, k.gameId(), k.market(), k.side(), k.playerId(), active, bumped, start);
    }

    @Test
    void boardNotLoadedNeverBumps() {
        PickKey a = key(1, "hit", "over", 100);
        List<ReconcileOp> ops = ModelPicksService.planReconcile(
            List.of(row(10, a, true, false, UPCOMING)), List.of(), false, NOW);
        assertThat(ops).isEmpty();
    }

    @Test
    void displacedPreGamePickIsBumped() {
        PickKey a = key(1, "hit", "over", 100);    // recorded, no longer on the board
        PickKey b = key(2, "hr", "over", 200);     // the better play now showing
        List<ReconcileOp> ops = ModelPicksService.planReconcile(
            List.of(row(10, a, true, false, UPCOMING)), List.of(b), true, NOW);
        assertThat(ops).containsExactly(new ReconcileOp(10, true, 0));
    }

    @Test
    void startedGameIsFrozenNotBumped() {
        PickKey a = key(1, "hit", "over", 100);
        PickKey b = key(2, "hr", "over", 200);
        List<ReconcileOp> ops = ModelPicksService.planReconcile(
            List.of(row(10, a, true, false, STARTED)), List.of(b), true, NOW);
        assertThat(ops).isEmpty();
    }

    @Test
    void returnedPickIsRePromotedAtItsBoardRank() {
        PickKey a = key(1, "hit", "over", 100);    // back on the board at rank 2
        PickKey b = key(2, "hr", "over", 200);
        List<ReconcileOp> ops = ModelPicksService.planReconcile(
            List.of(row(10, a, false, true, UPCOMING)), List.of(b, a), true, NOW);
        assertThat(ops).containsExactly(new ReconcileOp(10, false, 2));
    }

    @Test
    void alreadyCorrectActiveRowIsLeftAlone() {
        PickKey a = key(1, "hit", "over", 100);
        List<ReconcileOp> ops = ModelPicksService.planReconcile(
            List.of(row(10, a, true, false, UPCOMING)), List.of(a), true, NOW);
        assertThat(ops).isEmpty();
    }

    @Test
    void qualifyingBoardWithNoPicksStillBumpsPreGame() {
        PickKey a = key(1, "hit", "over", 100);
        List<ReconcileOp> ops = ModelPicksService.planReconcile(
            List.of(row(10, a, true, false, UPCOMING)), List.of(), true, NOW);
        assertThat(ops).containsExactly(new ReconcileOp(10, true, 0));
    }
}
