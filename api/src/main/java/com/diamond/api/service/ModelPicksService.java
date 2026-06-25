package com.diamond.api.service;

import com.diamond.api.dto.ModelPickResultDto;
import com.diamond.api.dto.ReconcileRequest.PickKey;
import com.diamond.api.repository.ModelPicksRepository;
import com.diamond.api.repository.ModelPicksRepository.ReconcileRow;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class ModelPicksService {

    private final ModelPicksRepository repo;

    public ModelPicksService(ModelPicksRepository repo) {
        this.repo = repo;
    }

    @Cacheable(cacheNames = "modelPicks", key = "#date.toString()")
    public List<ModelPickResultDto> picks(LocalDate date) {
        return repo.findByDate(date);
    }

    /**
     * Reconcile the recorded snapshot against the live board's current top set so a pick a
     * better late play has displaced falls to "Earlier today" immediately — rather than waiting
     * for the next record-picks cron run (which, if the game starts first, would freeze and never
     * record it). Never inserts (that needs the locked line/price, which the trusted cron owns):
     * only re-promotes a pick that's back in the top set and bumps one that's left it pre-game.
     * Evicts the cached read so {@link #picks} reflects the change.
     */
    @CacheEvict(cacheNames = "modelPicks", key = "#date.toString()")
    public void reconcile(LocalDate date, List<PickKey> activeKeys, boolean boardLoaded) {
        Instant now = Instant.now();
        for (ReconcileOp op : planReconcile(repo.findReconcileRows(date), activeKeys, boardLoaded, now)) {
            if (op.bump()) {
                repo.bump(op.id(), now);
            } else {
                repo.promote(op.id(), op.rank());
            }
        }
    }

    /** A planned change to one recorded row: bump (demote) or promote to {@code rank}. */
    record ReconcileOp(long id, boolean bump, int rank) {}

    /**
     * Pure (no IO) so it's unit-testable, mirroring the ingester's plan_reconcile minus insert:
     *   · key in the live top set but the row is bumped/inactive → re-promote at its board rank
     *   · key not in the top set, row still active, game not yet started → bump (displaced)
     *   · everything else (already-correct rows, started games) → leave as-is
     * When the board didn't load ({@code boardLoaded} false) nothing is bumped, so an empty pull
     * can never wipe legitimately-shown picks.
     */
    static List<ReconcileOp> planReconcile(List<ReconcileRow> rows, List<PickKey> activeKeys,
                                           boolean boardLoaded, Instant now) {
        List<ReconcileOp> ops = new ArrayList<>();
        if (!boardLoaded) {
            return ops;
        }
        Map<PickKey, Integer> rankByKey = new HashMap<>();
        for (int i = 0; i < activeKeys.size(); i++) {
            rankByKey.putIfAbsent(activeKeys.get(i), i + 1);
        }
        for (ReconcileRow row : rows) {
            Integer rank = rankByKey.get(row.key());
            if (rank != null) {
                if (!row.active() || row.bumped()) {
                    ops.add(new ReconcileOp(row.id(), false, rank));
                }
            } else if (row.active() && row.startTime() != null && row.startTime().isAfter(now)) {
                ops.add(new ReconcileOp(row.id(), true, 0));
            }
        }
        return ops;
    }
}
