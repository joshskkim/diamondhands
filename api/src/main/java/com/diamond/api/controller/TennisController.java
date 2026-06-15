package com.diamond.api.controller;

import com.diamond.api.dto.TennisMatchDetailDto;
import com.diamond.api.dto.TennisMatchDto;
import com.diamond.api.dto.TennisRankingDto;
import com.diamond.api.service.TennisService;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Set;

@RestController
@RequestMapping("/api/tennis")
public class TennisController {

    private static final Set<String> SURFACES = Set.of("all", "hard", "clay", "grass");

    private final TennisService tennisService;

    public TennisController(TennisService tennisService) {
        this.tennisService = tennisService;
    }

    /** Current scheduled slate with projections + best-line EV. */
    @GetMapping("/matches/today")
    public List<TennisMatchDto> today() {
        return tennisService.scheduledMatches();
    }

    @GetMapping("/matches/{matchId}")
    public TennisMatchDetailDto detail(@PathVariable long matchId) {
        return tennisService.matchDetail(matchId);
    }

    @GetMapping("/rankings")
    public List<TennisRankingDto> rankings(
            @RequestParam(defaultValue = "all") String surface,
            @RequestParam(defaultValue = "50") int limit) {
        String s = SURFACES.contains(surface) ? surface : "all";
        int capped = Math.min(Math.max(limit, 1), 200);
        return tennisService.rankings(s, capped);
    }
}
