package com.diamond.api.controller;

import com.diamond.api.dto.ModelPickResultDto;
import com.diamond.api.service.ModelPicksService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.List;

/**
 * Persisted Model's Picks with graded outcomes for a slate. Powers the ✓/✗ markers on
 * the home board (today's picks, graded as games finish) and the "Recent results"
 * recap (a prior slate). Defaults to today when no date is given.
 */
@RestController
@RequestMapping("/api/model-picks")
public class ModelPicksController {

    private final ModelPicksService service;

    public ModelPicksController(ModelPicksService service) {
        this.service = service;
    }

    @GetMapping
    public List<ModelPickResultDto> picks(
        @RequestParam(required = false)
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date) {
        return service.picks(date != null ? date : LocalDate.now());
    }
}
