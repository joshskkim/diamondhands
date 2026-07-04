package com.diamond.api.ai;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDate;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Per-user throttle for the expensive agent endpoint. Each agent call fans out into several Gemini
 * requests (the debate uses a pricier judge model), so an authenticated user could otherwise spam
 * it and run up real cost. In-memory is deliberate: this is single-instance cost/abuse protection,
 * not a distributed quota — a sliding 1-minute window plus a hard daily cap, both per user.
 */
@Component
public class AgentRateLimiter {

    private final int perMinute;
    private final int perDay;

    private final Map<Long, Deque<Long>> minuteWindows = new ConcurrentHashMap<>();
    private final Map<Long, DayCount> dailyCounts = new ConcurrentHashMap<>();

    public AgentRateLimiter(@Value("${app.agent.rate.per-minute:5}") int perMinute,
                            @Value("${app.agent.rate.per-day:100}") int perDay) {
        this.perMinute = perMinute;
        this.perDay = perDay;
    }

    /** Record one agent request for the user, or throw 429 when over a limit. */
    public void check(long userId) {
        long now = System.currentTimeMillis();
        Deque<Long> window = minuteWindows.computeIfAbsent(userId, k -> new ArrayDeque<>());
        // Synchronizing on the user's own window object also guards that user's daily counter,
        // since the same user always resolves to the same window instance.
        synchronized (window) {
            while (!window.isEmpty() && now - window.peekFirst() > 60_000L) {
                window.pollFirst();
            }
            if (window.size() >= perMinute) {
                throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS,
                    "You're sending requests too fast — give it a moment.");
            }
            LocalDate today = LocalDate.now();
            DayCount dc = dailyCounts.get(userId);
            if (dc == null || !dc.date().equals(today)) {
                dc = new DayCount(today, 0);
            }
            if (dc.count() >= perDay) {
                throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS,
                    "You've reached today's analyst limit. Try again tomorrow.");
            }
            window.addLast(now);
            dailyCounts.put(userId, new DayCount(today, dc.count() + 1));
        }
    }

    private record DayCount(LocalDate date, int count) {}
}
