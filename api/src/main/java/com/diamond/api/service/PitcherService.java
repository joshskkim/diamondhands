package com.diamond.api.service;

import com.diamond.api.dto.PitcherSkillDto;
import com.diamond.api.repository.PitcherRepository;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class PitcherService {

    private final PitcherRepository pitcherRepository;

    public PitcherService(PitcherRepository pitcherRepository) {
        this.pitcherRepository = pitcherRepository;
    }

    /** A pitcher's latest-season skill splits vs LHB/RHB (one row each). */
    @Cacheable(cacheNames = "pitcherSkill", key = "#pitcherId")
    public List<PitcherSkillDto> skill(int pitcherId) {
        return pitcherRepository.skill(pitcherId);
    }
}
