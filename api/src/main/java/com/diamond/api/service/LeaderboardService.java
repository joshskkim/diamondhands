package com.diamond.api.service;

import com.diamond.api.dto.PitcherDto;
import com.diamond.api.dto.PitchTypeLeaderboardDto;
import com.diamond.api.dto.PitchTypeRefDto;
import com.diamond.api.repository.PitchRepository;
import com.diamond.api.repository.PitchRepository.LeaderboardRow;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

@Service
public class LeaderboardService {

    /** Supported pitch types in display order, with friendly names. */
    private static final List<PitchTypeRefDto> PITCH_TYPES = List.of(
        new PitchTypeRefDto("FF", "4-Seam Fastball"),
        new PitchTypeRefDto("SI", "Sinker"),
        new PitchTypeRefDto("FC", "Cutter"),
        new PitchTypeRefDto("SL", "Slider"),
        new PitchTypeRefDto("CU", "Curveball"),
        new PitchTypeRefDto("CH", "Changeup"),
        new PitchTypeRefDto("FS", "Splitter"));

    private final PitchRepository pitchRepository;

    public LeaderboardService(PitchRepository pitchRepository) {
        this.pitchRepository = pitchRepository;
    }

    public List<PitchTypeRefDto> pitchTypes() {
        return PITCH_TYPES;
    }

    /**
     * Top batters playing on {@code date} whose opposing starter throws {@code pitch}
     * (usage ≥ 20%, batter ≥ 100 pitches seen), ranked by regressed xwOBA edge desc.
     * Cached per (pitch, date, limit): the underlying snapshot query is the heaviest in
     * the app, and the slate is fixed for a given date, so the 5-min TTL is safe.
     */
    @Cacheable(cacheNames = "pitchTypeLeaderboard", key = "#pitch + ':' + #date + ':' + #limit")
    public List<PitchTypeLeaderboardDto> pitchTypeLeaderboard(String pitch, LocalDate date, int limit) {
        List<PitchTypeLeaderboardDto> out = new ArrayList<>();
        for (LeaderboardRow r : pitchRepository.leaderboardCandidates(pitch, date)) {
            Double regressed = PitchRepository.regress(
                r.rawXwoba(), r.pitchesSeen(), r.leagueXwoba(), PitchRepository.REGRESSION_K_PITCHES_BATTER);
            if (regressed == null || r.leagueXwoba() == null) {
                continue;
            }
            double edge = regressed - r.leagueXwoba();
            out.add(new PitchTypeLeaderboardDto(
                new PitchTypeLeaderboardDto.LeaderboardPlayer(r.playerId(), r.playerName(), r.teamAbbr()),
                new PitcherDto(r.pitcherId(), r.pitcherName(), r.pitcherThrows()),
                round4(r.usageRate()),
                round4(regressed),
                round4(r.leagueXwoba()),
                round4(edge),
                r.pitchesSeen()));
        }
        out.sort(Comparator.comparingDouble(PitchTypeLeaderboardDto::edge).reversed());
        return out.size() > limit ? out.subList(0, limit) : out;
    }

    private static double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }
}
