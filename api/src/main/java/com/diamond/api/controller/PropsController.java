package com.diamond.api.controller;

import com.diamond.api.dto.PropBoardResponse;
import com.diamond.api.service.PropBoardService;
import com.diamond.api.service.SlateService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;

/** Model-first prop board: the most likely batter per prop market, odds optional. */
@RestController
@RequestMapping("/api/props")
public class PropsController {

    private final PropBoardService service;
    private final SlateService slateService;

    public PropsController(PropBoardService service, SlateService slateService) {
        this.service = service;
        this.slateService = slateService;
    }

    @GetMapping("/board")
    public PropBoardResponse board(
        @RequestParam(required = false)
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date
    ) {
        return service.board(date != null ? date : slateService.activeSlateDate());
    }
}
