package com.diamond.api.controller;

import com.diamond.api.dto.AccuracyResponse;
import com.diamond.api.service.AccuracyService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/accuracy")
public class AccuracyController {

    private final AccuracyService accuracyService;

    public AccuracyController(AccuracyService accuracyService) {
        this.accuracyService = accuracyService;
    }

    /** Rolling per-market accuracy trend + latest calibration for the current model version. */
    @GetMapping
    public AccuracyResponse accuracy(@RequestParam(defaultValue = "30") int days) {
        int safeDays = Math.max(7, Math.min(days, 180));
        return accuracyService.accuracy(safeDays);
    }
}
