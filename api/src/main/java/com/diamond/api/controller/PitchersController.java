package com.diamond.api.controller;

import com.diamond.api.dto.PitcherSkillDto;
import com.diamond.api.service.PitcherService;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/pitchers")
public class PitchersController {

    private final PitcherService pitcherService;

    public PitchersController(PitcherService pitcherService) {
        this.pitcherService = pitcherService;
    }

    @GetMapping("/{pitcherId}/skill")
    public List<PitcherSkillDto> skill(@PathVariable int pitcherId) {
        return pitcherService.skill(pitcherId);
    }
}
