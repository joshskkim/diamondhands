package com.diamond.api.controller;

import com.diamond.api.dto.GameOddsResponse;
import com.diamond.api.dto.GameProjectionsResponse;
import com.diamond.api.dto.TodayGameDto;
import com.diamond.api.service.GameService;
import com.diamond.api.service.LiveGameService;
import com.diamond.api.service.OddsService;
import com.diamond.api.service.ProjectionService;
import com.diamond.api.service.SlateService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;

@RestController
@RequestMapping("/api/games")
public class GamesController {

    private final GameService gameService;
    private final ProjectionService projectionService;
    private final OddsService oddsService;
    private final SlateService slateService;
    private final LiveGameService liveGameService;

    public GamesController(GameService gameService, ProjectionService projectionService,
                           OddsService oddsService, SlateService slateService,
                           LiveGameService liveGameService) {
        this.gameService = gameService;
        this.projectionService = projectionService;
        this.oddsService = oddsService;
        this.slateService = slateService;
        this.liveGameService = liveGameService;
    }

    @GetMapping("/today")
    public List<TodayGameDto> today() {
        return gameService.todayGames(slateService.activeSlateDate());
    }

    /** SSE stream of live in-game state deltas; one connection per browser tab. */
    @GetMapping(value = "/live/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter liveStream() {
        return liveGameService.subscribe();
    }

    @GetMapping("/{gameId}/projections")
    public GameProjectionsResponse projections(@PathVariable long gameId) {
        return projectionService.gameProjections(gameId);
    }

    @GetMapping("/{gameId}/odds")
    public GameOddsResponse odds(@PathVariable long gameId) {
        return oddsService.gameOdds(gameId);
    }
}
