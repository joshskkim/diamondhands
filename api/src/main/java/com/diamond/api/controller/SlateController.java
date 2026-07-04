package com.diamond.api.controller;

import com.diamond.api.service.SlateService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;

/**
 * Exposes the active slate date so out-of-process clients (the ingester's record-picks)
 * record the same slate users are actually shown, rather than the wall-clock date.
 */
@RestController
@RequestMapping("/api/slate")
public class SlateController {

    private final SlateService slateService;

    public SlateController(SlateService slateService) {
        this.slateService = slateService;
    }

    @GetMapping("/active")
    public ActiveSlate active() {
        return new ActiveSlate(slateService.activeSlateDate().toString());
    }

    public record ActiveSlate(String date) {}
}
