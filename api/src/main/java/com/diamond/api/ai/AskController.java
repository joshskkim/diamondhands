package com.diamond.api.ai;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * "Ask Diamond" SSE endpoint. POST a question; the answer streams back as Server-Sent Events:
 * a live {@code status} feed (one per tool the model calls), then a final {@code answer} and the
 * {@code sources} (tools used). Returns 503 when the feature is disabled (no API key).
 */
@RestController
@RequestMapping("/api/ask")
public class AskController {

    private static final int MAX_QUESTION_LEN = 1000;
    private static final long STREAM_TIMEOUT_MS = 120_000L;

    private final AskService askService;
    private final ObjectMapper mapper;
    private final ExecutorService executor;

    public AskController(AskService askService, ObjectMapper mapper) {
        this.askService = askService;
        this.mapper = mapper;
        AtomicInteger n = new AtomicInteger();
        this.executor = Executors.newFixedThreadPool(4, r -> {
            Thread t = new Thread(r, "ask-sse-" + n.incrementAndGet());
            t.setDaemon(true);
            return t;
        });
    }

    public record AskRequest(String question) {}

    @PostMapping(produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter ask(@RequestBody AskRequest request) {
        if (!askService.isAvailable()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "AI assistant is disabled");
        }
        String raw = request == null || request.question() == null ? "" : request.question().trim();
        if (raw.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "question is required");
        }
        String question = raw.length() > MAX_QUESTION_LEN ? raw.substring(0, MAX_QUESTION_LEN) : raw;

        SseEmitter emitter = new SseEmitter(STREAM_TIMEOUT_MS);
        executor.submit(() -> {
            SseSink sink = new SseSink(emitter);
            try {
                askService.ask(question, sink);
            } catch (Exception e) {
                sink.error("Something went wrong answering that.");
            } finally {
                emitter.complete();
            }
        });
        return emitter;
    }

    /** Adapts {@link AskService.AskSink} onto the SSE stream; swallows post-disconnect writes. */
    private final class SseSink implements AskService.AskSink {
        private final SseEmitter emitter;

        SseSink(SseEmitter emitter) {
            this.emitter = emitter;
        }

        @Override
        public void status(String toolName, String label) {
            send("status", Map.of("tool", toolName, "label", label));
        }

        @Override
        public void links(List<LinkRef> links) {
            send("links", Map.of("links", links));
        }

        @Override
        public void answer(String text) {
            send("answer", Map.of("text", text));
        }

        @Override
        public void sources(List<String> toolNames) {
            send("sources", Map.of("tools", toolNames));
        }

        @Override
        public void error(String message) {
            send("error", Map.of("message", message));
        }

        private void send(String event, Object data) {
            try {
                emitter.send(SseEmitter.event().name(event).data(mapper.writeValueAsString(data)));
            } catch (IOException | IllegalStateException e) {
                // Client disconnected or stream already complete — nothing to do.
            }
        }
    }
}
