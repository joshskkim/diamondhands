package com.diamond.api.service;

import com.diamond.api.dto.PitcherDto;
import com.diamond.api.dto.PitchTypeLeaderboardDto;
import com.diamond.api.dto.PitchTypeRefDto;
import com.diamond.api.repository.PitchRepository;
import com.diamond.api.repository.PitchRepository.LeaderboardRow;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.observation.annotation.Observed;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.ReentrantLock;

@Service
public class LeaderboardService {

    // Package-private so LeaderboardServiceTest names the cache instead of duplicating it.
    static final String CACHE = "pitchTypeLeaderboard";

    /** Supported pitch types in display order, with friendly names. */
    private static final List<PitchTypeRefDto> PITCH_TYPES = List.of(
        new PitchTypeRefDto("FF", "4-Seam Fastball"),
        new PitchTypeRefDto("SI", "Sinker"),
        new PitchTypeRefDto("FC", "Cutter"),
        new PitchTypeRefDto("SL", "Slider"),
        new PitchTypeRefDto("CU", "Curveball"),
        new PitchTypeRefDto("CH", "Changeup"),
        new PitchTypeRefDto("FS", "Splitter"));

    private final PitchRepository pitchRepository;
    private final CacheManager cacheManager;
    private final Counter dbQueries;
    // One lock per cache key, so concurrent cold misses for the SAME key serialize
    // (single-flight) while different keys stay independent.
    private final ConcurrentHashMap<String, ReentrantLock> keyLocks = new ConcurrentHashMap<>();

    public LeaderboardService(PitchRepository pitchRepository, CacheManager cacheManager,
                              MeterRegistry meterRegistry) {
        this.pitchRepository = pitchRepository;
        this.cacheManager = cacheManager;
        // Counts actual executions of the heavy leaderboard query — the metric single-flight
        // drives toward 1 per key under a concurrent cold burst.
        this.dbQueries = Counter.builder("leaderboard.db.query")
            .description("Executions of the heavy pitch-type leaderboard query")
            .register(meterRegistry);
    }

    public List<PitchTypeRefDto> pitchTypes() {
        return PITCH_TYPES;
    }

    /**
     * Top batters playing on {@code date} whose opposing starter throws {@code pitch}
     * (usage ≥ 20%, batter ≥ 100 pitches seen), ranked by regressed xwOBA edge desc.
     * Cached per (pitch, date, limit): the underlying snapshot query is the heaviest in
     * the app, and the slate is fixed for a given date, so the 5-min TTL is safe.
     *
     * The {@code @Cacheable} below serves the common hit path. On a MISS this method body
     * runs and applies an explicit single-flight guard: concurrent cold requests for the
     * same key serialize on a per-key lock so exactly one runs the heavy query while the
     * rest reuse its result. Without it, 15 concurrent cold requests ran 15 copies of the
     * query and 5 failed with CannotGetJdbcConnectionException (HikariCP pool exhausted).
     * (Spring's {@code @Cacheable(sync=true)} is the declarative equivalent but deadlocks
     * with this RedisCacheManager, so we guard it ourselves.)
     */
    @Observed(name = "leaderboard.pitchType", contextualName = "leaderboard.pitchType")
    @Cacheable(cacheNames = CACHE, key = "#pitch + ':' + #date + ':' + #limit")
    public List<PitchTypeLeaderboardDto> pitchTypeLeaderboard(String pitch, LocalDate date, int limit) {
        String key = pitch + ":" + date + ":" + limit;
        ReentrantLock lock = keyLocks.computeIfAbsent(key, k -> new ReentrantLock());
        lock.lock();
        try {
            // A peer may have populated the cache while we waited on the lock.
            Cache cache = cacheManager.getCache(CACHE);
            if (cache != null) {
                Cache.ValueWrapper hit = cache.get(key);
                if (hit != null) {
                    @SuppressWarnings("unchecked")
                    List<PitchTypeLeaderboardDto> peer = (List<PitchTypeLeaderboardDto>) hit.get();
                    return peer;
                }
            }
            List<PitchTypeLeaderboardDto> result = computeLeaderboard(pitch, date, limit);
            // Publish before releasing the lock so waiting peers find it (closes the herd
            // window); @Cacheable also stores it on return — an idempotent overwrite.
            if (cache != null) {
                cache.put(key, result);
            }
            return result;
        } finally {
            lock.unlock();
            keyLocks.remove(key, lock);
        }
    }

    private List<PitchTypeLeaderboardDto> computeLeaderboard(String pitch, LocalDate date, int limit) {
        dbQueries.increment();
        List<PitchTypeLeaderboardDto> out = new ArrayList<>();
        for (LeaderboardRow r : pitchRepository.leaderboardCandidates(pitch, date)) {
            Double regressed = PitchRepository.regress(
                r.rawXwoba(), r.pitchesSeen(), r.leagueXwoba(), PitchRepository.REGRESSION_K_PITCHES_BATTER);
            if (regressed == null || r.leagueXwoba() == null) {
                continue;
            }
            double edge = regressed - r.leagueXwoba();
            out.add(new PitchTypeLeaderboardDto(
                new PitchTypeLeaderboardDto.LeaderboardPlayer(r.playerId(), r.playerName(), r.teamAbbr()),
                new PitcherDto(r.pitcherId(), r.pitcherName(), r.pitcherThrows()),
                round4(r.usageRate()),
                round4(regressed),
                round4(r.leagueXwoba()),
                round4(edge),
                r.pitchesSeen()));
        }
        out.sort(Comparator.comparingDouble(PitchTypeLeaderboardDto::edge).reversed());
        // Return a fresh ArrayList (not a subList view) so it serializes cleanly into Redis.
        return out.size() > limit ? new ArrayList<>(out.subList(0, limit)) : out;
    }

    private static double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }
}
