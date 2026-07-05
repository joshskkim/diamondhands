package com.diamond.api.controller;

import com.diamond.api.dto.BoomPickDto;
import com.diamond.api.service.LottoService;
import com.diamond.api.service.SlateService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;

/** The "Lotto of the Day" — one HR boom pick for the slate, or 204 when none qualifies. */
@RestController
@RequestMapping("/api/lotto")
public class LottoController {

    private final LottoService lottoService;
    private final SlateService slateService;

    public LottoController(LottoService lottoService, SlateService slateService) {
        this.lottoService = lottoService;
        this.slateService = slateService;
    }

    @GetMapping
    public ResponseEntity<BoomPickDto> lotto(
        @RequestParam(required = false)
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date
    ) {
        LocalDate target = date != null ? date : slateService.activeSlateDate();
        BoomPickDto pick = lottoService.lottoOfTheDay(target);
        return pick == null ? ResponseEntity.noContent().build() : ResponseEntity.ok(pick);
    }
}
