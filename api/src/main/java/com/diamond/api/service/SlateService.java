package com.diamond.api.service;

import com.diamond.api.repository.SlateRepository;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.ZoneId;

/**
 * Single source of truth for "which slate is the board showing right now". Every
 * today-scoped endpoint resolves its default date here instead of {@code LocalDate.now()}
 * (which used the server's UTC clock and flipped at the wrong instant). See
 * {@link SlateRepository} for the "ready" definition.
 *
 * <p>Memoized in-process for {@value #TTL_MS} ms (not the Redis cache: a flip should
 * propagate within a minute, and a bare LocalDate isn't worth a JSON cache round-trip)
 * so the resolver's two MAX queries don't run on every today-scoped request.
 */
@Service
public class SlateService {

    private static final ZoneId EASTERN = ZoneId.of("America/New_York");
    private static final long TTL_MS = 60_000;

    private final SlateRepository slateRepository;

    private volatile LocalDate cached;
    private volatile long cachedAtMs;

    public SlateService(SlateRepository slateRepository) {
        this.slateRepository = slateRepository;
    }

    public LocalDate activeSlateDate() {
        LocalDate snapshot = cached;
        if (snapshot != null && System.currentTimeMillis() - cachedAtMs < TTL_MS) {
            return snapshot;
        }
        LocalDate resolved = resolve();
        cached = resolved;
        cachedAtMs = System.currentTimeMillis();
        return resolved;
    }

    private LocalDate resolve() {
        LocalDate et = LocalDate.now(EASTERN);
        LocalDate ready = slateRepository.latestReadySlate(et);
        if (ready != null) {
            return ready;
        }
        LocalDate latest = slateRepository.latestSlateWithGames(et);
        return latest != null ? latest : et;
    }
}
