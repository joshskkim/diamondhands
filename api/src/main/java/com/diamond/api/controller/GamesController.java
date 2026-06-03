package com.diamond.api.controller;

import com.diamond.api.dto.GameOddsResponse;
import com.diamond.api.dto.GameProjectionsResponse;
import com.diamond.api.dto.TodayGameDto;
import com.diamond.api.service.GameService;
import com.diamond.api.service.OddsService;
import com.diamond.api.service.ProjectionService;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.util.List;

@RestController
@RequestMapping("/api/games")
public class GamesController {

    private final GameService gameService;
    private final ProjectionService projectionService;
    private final OddsService oddsService;

    public GamesController(GameService gameService, ProjectionService projectionService,
                           OddsService oddsService) {
        this.gameService = gameService;
        this.projectionService = projectionService;
        this.oddsService = oddsService;
    }

    @GetMapping("/today")
    public List<TodayGameDto> today() {
        return gameService.todayGames(LocalDate.now());
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
