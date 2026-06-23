package com.diamond.api.controller;

import com.diamond.api.dto.PitchTypeLeaderboardDto;
import com.diamond.api.dto.PitchTypeRefDto;
import com.diamond.api.service.LeaderboardService;
import com.diamond.api.service.SlateService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.util.List;

@RestController
@RequestMapping("/api/leaderboards")
public class LeaderboardController {

    private final LeaderboardService leaderboardService;
    private final SlateService slateService;

    public LeaderboardController(LeaderboardService leaderboardService, SlateService slateService) {
        this.leaderboardService = leaderboardService;
        this.slateService = slateService;
    }

    /** Supported pitch types with friendly names. */
    @GetMapping("/pitch-types")
    public List<PitchTypeRefDto> pitchTypes() {
        return leaderboardService.pitchTypes();
    }

    /** Top batters today vs a given pitch type, by regressed xwOBA edge. */
    @GetMapping("/pitch-type")
    public List<PitchTypeLeaderboardDto> pitchTypeLeaderboard(
        @RequestParam("pitch") String pitch,
        @RequestParam(value = "date", required = false)
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
        @RequestParam(value = "limit", defaultValue = "20") int limit) {
        LocalDate target = date != null ? date : slateService.activeSlateDate();
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return leaderboardService.pitchTypeLeaderboard(pitch.toUpperCase(), target, safeLimit);
    }
}
