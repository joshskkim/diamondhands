package com.diamond.api.controller;

import com.diamond.api.auth.AuthUser;
import com.diamond.api.dto.TrackerResponse;
import com.diamond.api.service.TrackerService;
import com.diamond.api.service.TrackerService.TailResult;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * The personal Tracker (authenticated). {@code GET /api/tracker} returns the user's tailed picks +
 * logged bets graded with ROI/CLV; {@code POST /api/tracker/tail} tails a board pick (computing a
 * Kelly stake). Both require a session — GET /api/tracker is explicitly authenticated in
 * SecurityConfig (the default permits GET /api/**).
 */
@RestController
@RequestMapping("/api/tracker")
public class TrackerController {

    private final TrackerService tracker;

    public TrackerController(TrackerService tracker) {
        this.tracker = tracker;
    }

    public record TailRequest(long gameId, String market, String side, Double line, Integer playerId,
                              String playerName, Integer priceAmerican, String book,
                              Double modelProb, Double fairProb, Double confidence) {}

    @GetMapping
    public TrackerResponse tracker(@AuthenticationPrincipal AuthUser user) {
        requireUser(user);
        return tracker.tracked(user.id());
    }

    @PostMapping("/tail")
    public TailResult tail(@AuthenticationPrincipal AuthUser user, @RequestBody TailRequest req) {
        requireUser(user);
        if (req == null || req.priceAmerican() == null || req.modelProb() == null || req.fairProb() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "missing pick fields");
        }
        return tracker.tail(user.id(), req.gameId(), req.market(), req.side(), req.line(),
            req.playerId(), req.playerName(), req.priceAmerican(), req.book(),
            req.modelProb(), req.fairProb(), req.confidence());
    }

    private static void requireUser(AuthUser user) {
        if (user == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "sign in required");
        }
    }
}
