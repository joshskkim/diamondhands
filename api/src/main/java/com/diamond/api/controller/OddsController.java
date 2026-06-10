package com.diamond.api.controller;

import com.diamond.api.dto.BatterPropOddsDto;
import com.diamond.api.dto.BestPlayDto;
import com.diamond.api.service.OddsService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.util.List;

@RestController
@RequestMapping("/api/odds")
public class OddsController {

    private final OddsService oddsService;

    public OddsController(OddsService oddsService) {
        this.oddsService = oddsService;
    }

    /** Today's Best Lines board: model-edged selections across the slate, sorted by EV%. */
    @GetMapping("/best")
    public List<BestPlayDto> best(
        @RequestParam(required = false)
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
        @RequestParam(defaultValue = "50") int limit
    ) {
        LocalDate target = date != null ? date : LocalDate.now();
        int safeLimit = Math.min(Math.max(limit, 1), 200);
        List<BestPlayDto> plays = oddsService.bestPlays(target);
        return plays.size() > safeLimit ? plays.subList(0, safeLimit) : plays;
    }

    /** Batter prop over-prices for the slate (BetRivers-first), for Best Bets. */
    @GetMapping("/props")
    public List<BatterPropOddsDto> props(
        @RequestParam(required = false)
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date
    ) {
        LocalDate target = date != null ? date : LocalDate.now();
        return oddsService.batterProps(target);
    }
}
