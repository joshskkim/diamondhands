package com.diamond.api.controller;

import com.diamond.api.dto.ModelPickResultDto;
import com.diamond.api.dto.ReconcileRequest;
import com.diamond.api.service.ModelPicksService;
import com.diamond.api.service.SlateService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
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

    /**
     * Record which earlier picks the live board has displaced, posted by the home page when its
     * current top set diverges from the recorded snapshot. Demote/promote-only (never inserts), so
     * it keeps "Earlier today" and the track-record in step without waiting for the record-picks
     * cron. An empty {@code activeKeys} is a no-op on the service side.
     */
    @PostMapping("/reconcile")
    public void reconcile(@RequestBody ReconcileRequest req) {
        LocalDate date = req.date() != null ? req.date() : slateService.activeSlateDate();
        service.reconcile(date, req.activeKeys() != null ? req.activeKeys() : List.of(),
            req.boardLoaded());
    }
}
