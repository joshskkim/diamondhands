package com.diamond.api.controller;

import com.diamond.api.dto.ModelPickResultDto;
import com.diamond.api.service.ModelPicksService;
import com.diamond.api.service.SlateService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.List;

/**
 * Persisted Model's Picks with graded outcomes for a slate — the board itself: the web
 * renders these rows directly (active rows are today's picks, bumped rows the "earlier"
 * extras). Powers the ✓/✗ markers on the home board and the "Recent results" recap.
 * Defaults to the active slate when no date is given.
 */
@RestController
@RequestMapping("/api/model-picks")
public class ModelPicksController {

    private final ModelPicksService service;
    private final SlateService slateService;

    public ModelPicksController(ModelPicksService service, SlateService slateService) {
        this.service = service;
        this.slateService = slateService;
    }

    @GetMapping
    public List<ModelPickResultDto> picks(
        @RequestParam(required = false)
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date) {
        return service.picks(date != null ? date : slateService.activeSlateDate());
    }
}
