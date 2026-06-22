package com.diamond.api.controller;

import com.diamond.api.dto.PlayerResultsResponse;
import com.diamond.api.service.ResultsService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;

/** Actual per-player results for a slate, for client-side ✓/✗ grading of prop picks. */
@RestController
@RequestMapping("/api/results")
public class ResultsController {

    private final ResultsService service;

    public ResultsController(ResultsService service) {
        this.service = service;
    }

    @GetMapping("/players")
    public PlayerResultsResponse players(
        @RequestParam(required = false)
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date
    ) {
        return service.playerResults(date != null ? date : LocalDate.now());
    }
}
