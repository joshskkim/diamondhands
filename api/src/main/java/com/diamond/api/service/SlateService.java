package com.diamond.api.service;

import com.diamond.api.repository.SlateRepository;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.ZoneId;

/**
 * Single source of truth for "which slate is the board showing right now". Every
 * today-scoped endpoint resolves its default date here instead of {@code LocalDate.now()}
 * (which used the server's UTC clock and flipped at the wrong instant).
 *
 * <p>The board holds yesterday's slate overnight and flips to the new day when the
 * <em>morning slate is pulled</em> — i.e. as soon as today's {@code games} rows exist
 * (the ingester's {@code daily-slate} step, ~9am ET). It does not wait for lineups or
 * projections, so the board may show its "projections fill in soon" placeholder through
 * the morning until each game's lineup posts in the afternoon. See {@link SlateRepository}.
 *
 * <p>Memoized in-process for {@value #TTL_MS} ms (not the Redis cache: a flip should
 * propagate within a minute, and a bare LocalDate isn't worth a JSON cache round-trip)
 * so the resolver's MAX query doesn't run on every today-scoped request.
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
        LocalDate latest = slateRepository.latestSlateWithGames(et);
        return latest != null ? latest : et;
    }
}
