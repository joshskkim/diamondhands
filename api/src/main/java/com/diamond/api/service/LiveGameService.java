package com.diamond.api.service;

import com.diamond.api.dto.LiveGameDto;
import com.diamond.api.repository.GameRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Pushes live in-game state to subscribed browsers over Server-Sent Events.
 *
 * <p>A single {@link Scheduled} task polls the lean {@code games.live_*} read once per
 * tick, diffs it against the last broadcast, and emits only the games that changed as a
 * named {@code games} event ({@code LiveGameDto[]} JSON) — so N connected clients cost one
 * DB query, not N. A {@code :keepalive} comment goes out every tick regardless so idle
 * connections (and the reverse proxy) don't time out. New subscribers immediately receive
 * the current full snapshot.
 *
 * <p>This never touches the Final grading path: the live columns are independent of
 * {@code home_score}/{@code away_score} (see V60__live_game_state.sql).
 */
@Service
public class LiveGameService {

    private static final Logger log = LoggerFactory.getLogger(LiveGameService.class);

    private final GameRepository gameRepository;
    private final SlateService slateService;

    private final CopyOnWriteArrayList<SseEmitter> emitters = new CopyOnWriteArrayList<>();
    /** Last broadcast state, keyed by gameId — read on subscribe, written by the scheduler. */
    private volatile Map<Long, LiveGameDto> lastByGame = Map.of();

    public LiveGameService(GameRepository gameRepository, SlateService slateService) {
        this.gameRepository = gameRepository;
        this.slateService = slateService;
    }

    /** Register a new SSE subscriber and send it the current live snapshot. */
    public SseEmitter subscribe() {
        SseEmitter emitter = new SseEmitter(0L); // no timeout; heartbeat keeps it alive
        emitter.onCompletion(() -> emitters.remove(emitter));
        emitter.onTimeout(() -> emitters.remove(emitter));
        emitter.onError(e -> emitters.remove(emitter));
        emitters.add(emitter);
        List<LiveGameDto> snapshot = List.copyOf(lastByGame.values());
        if (!snapshot.isEmpty()) {
            sendTo(emitter, snapshot);
        }
        return emitter;
    }

    /** Poll live state, broadcast only changed games, and heartbeat every tick. */
    @Scheduled(fixedDelay = 10_000L)
    public void broadcastTick() {
        if (emitters.isEmpty()) {
            return; // nothing connected — don't query the DB
        }
        List<LiveGameDto> current;
        try {
            current = gameRepository.findLiveByDate(slateService.activeSlateDate());
        } catch (Exception e) {
            log.warn("live poll failed: {}", e.toString());
            return;
        }

        Map<Long, LiveGameDto> currentByGame = new HashMap<>(current.size());
        for (LiveGameDto g : current) {
            currentByGame.put(g.gameId(), g);
        }

        List<LiveGameDto> changed = current.stream()
            .filter(g -> !g.equals(lastByGame.get(g.gameId())))
            .toList();
        lastByGame = currentByGame;

        for (SseEmitter emitter : emitters) {
            if (!changed.isEmpty()) {
                sendTo(emitter, changed);
            }
            heartbeat(emitter);
        }
    }

    private void sendTo(SseEmitter emitter, List<LiveGameDto> games) {
        try {
            emitter.send(SseEmitter.event().name("games").data(games));
        } catch (IOException | IllegalStateException e) {
            emitter.complete();
            emitters.remove(emitter);
        }
    }

    private void heartbeat(SseEmitter emitter) {
        try {
            emitter.send(SseEmitter.event().comment("keepalive"));
        } catch (IOException | IllegalStateException e) {
            emitter.complete();
            emitters.remove(emitter);
        }
    }
}
