package com.diamond.api.controller;

import com.diamond.api.ai.DebateOrchestrator;
import com.diamond.api.ai.NoOpSink;
import com.google.genai.Client;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;

/**
 * Server-to-server endpoint that runs the bull/skeptic/judge debate on a single candidate pick and
 * returns the judge's {@link DebateOrchestrator.Verdict}. Called by the ingester's record-picks to
 * gate Model's Picks. Protected by a shared internal key (NOT a user session — it's expensive and
 * not for browsers); returns 503 when AI is disabled so the caller falls back to mechanical
 * promotion (the gate is additive — see V64).
 */
@RestController
@RequestMapping("/api/debate")
public class DebateController {

    private final DebateOrchestrator debate;
    private final ObjectProvider<Client> clientProvider;
    private final String internalKey;

    public DebateController(DebateOrchestrator debate, ObjectProvider<Client> clientProvider,
                            @Value("${app.agent.internal-key:}") String internalKey) {
        this.debate = debate;
        this.clientProvider = clientProvider;
        this.internalKey = internalKey;
    }

    public record DebateRequest(long gameId, String market, String side, Double line, Integer playerId,
                                String playerName, Integer priceAmerican, Double modelProb, Double fairProb) {}

    @PostMapping("/pick")
    public DebateOrchestrator.Verdict debatePick(
            @RequestHeader(value = "X-Internal-Key", required = false) String key,
            @RequestBody DebateRequest req) {
        if (internalKey.isBlank() || !constantTimeEquals(internalKey, key)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "internal endpoint");
        }
        Client client = clientProvider.getIfAvailable();
        if (client == null) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "AI disabled");
        }
        DebateOrchestrator.Candidate c = new DebateOrchestrator.Candidate(
            req.gameId(), req.market(), req.side(), req.line(), req.playerId(),
            req.playerName(), req.priceAmerican(), req.modelProb(), req.fairProb());
        return debate.debate(client, c, NoOpSink.INSTANCE, null);
    }

    private static boolean constantTimeEquals(String a, String b) {
        if (b == null) {
            return false;
        }
        byte[] x = a.getBytes(StandardCharsets.UTF_8);
        byte[] y = b.getBytes(StandardCharsets.UTF_8);
        if (x.length != y.length) {
            return false;
        }
        int r = 0;
        for (int i = 0; i < x.length; i++) {
            r |= x[i] ^ y[i];
        }
        return r == 0;
    }
}
