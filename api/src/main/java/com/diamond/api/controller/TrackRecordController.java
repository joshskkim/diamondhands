package com.diamond.api.controller;

import com.diamond.api.dto.TrackRecordResponse;
import com.diamond.api.service.TrackRecordService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * The live track record of the published Model's Picks (record / units / ROI over a trailing
 * window). Powers the Report Card page. {@code days} defaults to 60; a large value (e.g. 36500)
 * yields the all-time record.
 */
@RestController
@RequestMapping("/api/track-record")
public class TrackRecordController {

    private final TrackRecordService service;

    public TrackRecordController(TrackRecordService service) {
        this.service = service;
    }

    @GetMapping
    public TrackRecordResponse trackRecord(@RequestParam(defaultValue = "60") int days) {
        return service.trackRecord(days);
    }
}
