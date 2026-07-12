package com.diamond.api.service;

import com.diamond.api.dto.PitchTypeLeaderboardDto;
import com.diamond.api.repository.PitchRepository;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.cache.concurrent.ConcurrentMapCacheManager;
import org.springframework.cache.support.NoOpCacheManager;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Verifies the pitch-type leaderboard applies empirical-Bayes regression and returns
 * rows sorted by xwOBA edge descending, and that the single-flight guard collapses a
 * concurrent cold burst to one execution of the heavy query. Uses a stub repository
 * (no DB / Spring context).
 */
class LeaderboardServiceTest {

    /** Fixed so every thread in a burst shares one cache key. */
    private static final LocalDate DATE = LocalDate.of(2026, 6, 14);
    private static final int BURST = 20;

    private static PitchRepository repoReturning(List<PitchRepository.LeaderboardRow> rows) {
        return new PitchRepository(null) {
            @Override
            public List<LeaderboardRow> leaderboardCandidates(String pitch, LocalDate date) {
                return rows;
            }
        };
    }

    /** Service wired with no-op cache + a throwaway meter registry (no Spring context). */
    private static LeaderboardService service(List<PitchRepository.LeaderboardRow> rows) {
        return new LeaderboardService(repoReturning(rows), new NoOpCacheManager(), new SimpleMeterRegistry());
    }

    /** Counts query executions and sleeps, so a herd reliably overlaps the first computation. */
    private static PitchRepository countingRepo(AtomicInteger calls) {
        return new PitchRepository(null) {
            @Override
            public List<LeaderboardRow> leaderboardCandidates(String pitch, LocalDate date) {
                calls.incrementAndGet();
                try {
                    Thread.sleep(50);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                return List.of(
                    new LeaderboardRow(1, "A", "AAA", 10, "P1", "R", 0.50, 0.400, 1000, 0.300));
            }
        };
    }

    /** Fires BURST cold requests for the same key, all released together. */
    private static List<List<PitchTypeLeaderboardDto>> burst(LeaderboardService svc) throws Exception {
        var pool = Executors.newFixedThreadPool(BURST);
        var start = new CountDownLatch(1);
        List<Future<List<PitchTypeLeaderboardDto>>> futures = new ArrayList<>();
        for (int i = 0; i < BURST; i++) {
            futures.add(pool.submit(() -> {
                start.await();
                return svc.pitchTypeLeaderboard("FF", DATE, 20);
            }));
        }
        start.countDown();
        pool.shutdown();
        assertThat(pool.awaitTermination(30, TimeUnit.SECONDS)).isTrue();

        List<List<PitchTypeLeaderboardDto>> results = new ArrayList<>();
        for (var f : futures) {
            results.add(f.get());
        }
        return results;
    }

    private static double dbQueries(MeterRegistry registry) {
        return registry.get("leaderboard.db.query").counter().count();
    }

    @Test
    void leaderboardSortsByEdgeDescAndRegresses() {
        // A: .400 raw over 1000 pitches vs league .300 → regressed ≈ .391, edge ≈ +.091
        // C: .360 raw over  200 pitches vs league .300 → regressed ≈ .340, edge ≈ +.040
        // B: .250 raw over 1000 pitches vs league .300 → regressed ≈ .255, edge ≈ -.046
        var rows = List.of(
            new PitchRepository.LeaderboardRow(1, "A", "AAA", 10, "P1", "R", 0.50, 0.400, 1000, 0.300),
            new PitchRepository.LeaderboardRow(2, "B", "BBB", 11, "P2", "L", 0.40, 0.250, 1000, 0.300),
            new PitchRepository.LeaderboardRow(3, "C", "CCC", 12, "P3", "R", 0.30, 0.360, 200, 0.300));

        var out = service(rows).pitchTypeLeaderboard("FF", LocalDate.now(), 20);

        assertThat(out).hasSize(3);
        assertThat(out.stream().map(r -> r.player().id())).containsExactly(1, 3, 2);
        // Strictly descending edges.
        assertThat(out.get(0).edge()).isGreaterThan(out.get(1).edge());
        assertThat(out.get(1).edge()).isGreaterThan(out.get(2).edge());
        // Regression pulls the 200-pitch sample further toward league than the raw value.
        assertThat(out.get(1).batterXwoba()).isLessThan(0.360).isGreaterThan(0.300);
    }

    @Test
    void respectsLimit() {
        var rows = List.of(
            new PitchRepository.LeaderboardRow(1, "A", "AAA", 10, "P1", "R", 0.50, 0.400, 1000, 0.300),
            new PitchRepository.LeaderboardRow(2, "B", "BBB", 11, "P2", "L", 0.40, 0.380, 1000, 0.300));
        var out = service(rows).pitchTypeLeaderboard("FF", LocalDate.now(), 1);
        assertThat(out).hasSize(1);
        assertThat(out.get(0).player().id()).isEqualTo(1);  // highest edge kept
    }

    @Test
    void pitchTypesHasSevenBuckets() {
        var types = service(List.of()).pitchTypes();
        assertThat(types).hasSize(7);
        assertThat(types.stream().map(t -> t.code()))
            .containsExactly("FF", "SI", "FC", "SL", "CU", "CH", "FS");
    }

    /**
     * The production path: with a real cache behind it, the single-flight guard lets one
     * thread run the heavy query while the rest reuse its result. Regression test for the
     * pool-exhaustion meltdown (see docs/observability-and-perf.md §3) — before the guard,
     * a burst this size ran BURST copies of the query and drained the 10-connection pool.
     */
    @Test
    void concurrentColdMissesRunTheQueryOnce() throws Exception {
        var calls = new AtomicInteger();
        var registry = new SimpleMeterRegistry();
        var svc = new LeaderboardService(
            countingRepo(calls), new ConcurrentMapCacheManager(LeaderboardService.CACHE), registry);

        var results = burst(svc);

        assertThat(calls).hasValue(1);
        assertThat(dbQueries(registry)).isEqualTo(1.0);
        assertThat(results).hasSize(BURST).allSatisfy(r -> assertThat(r).isEqualTo(results.get(0)));
    }

    /**
     * The {@code loadtest}-profile path ({@code spring.cache.type: none}): the peer-check
     * cannot hit a no-op cache, so every waiter recomputes. Requests serialize on the per-key
     * lock rather than saturating the pool — which is why the archived cache-off stress run
     * (loadtest/results/leaderboard-after.json) shows 0% errors but a multi-second p95.
     */
    @Test
    void cacheOffMakesEveryWaiterRecompute() throws Exception {
        var calls = new AtomicInteger();
        var registry = new SimpleMeterRegistry();
        var svc = new LeaderboardService(countingRepo(calls), new NoOpCacheManager(), registry);

        burst(svc);

        assertThat(calls).hasValue(BURST);
        assertThat(dbQueries(registry)).isEqualTo((double) BURST);
    }
}
