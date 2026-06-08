package com.diamond.api.controller;

import com.diamond.api.dto.MostLikelyResponse;
import com.diamond.api.service.MostLikelyService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;

/** "Most Likely" board: the game simulator's headline picks for a slate. */
@RestController
@RequestMapping("/api/most-likely")
public class MostLikelyController {

    private final MostLikelyService service;

    public MostLikelyController(MostLikelyService service) {
        this.service = service;
    }

    @GetMapping
    public MostLikelyResponse board(
        @RequestParam(required = false)
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date
    ) {
        return service.board(date != null ? date : LocalDate.now());
    }
}
