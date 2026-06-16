package com.diamond.api.service;

import com.diamond.api.dto.TennisAccuracyDto;
import com.diamond.api.dto.TennisMatchDetailDto;
import com.diamond.api.dto.TennisMatchDto;
import com.diamond.api.dto.TennisRankingDto;
import com.diamond.api.repository.TennisRepository;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class TennisService {

    /** Rankings hide players with thin samples on the surface. */
    private static final int RANKINGS_MIN_MATCHES = 20;

    private final TennisRepository tennisRepository;

    public TennisService(TennisRepository tennisRepository) {
        this.tennisRepository = tennisRepository;
    }

    @Cacheable(cacheNames = "tennis:matches", key = "'slate'")
    public List<TennisMatchDto> scheduledMatches() {
        return tennisRepository.findScheduledMatches();
    }

    @Cacheable(cacheNames = "tennis:match", key = "#matchId")
    public TennisMatchDetailDto matchDetail(long matchId) {
        return tennisRepository.findMatchDetail(matchId);
    }

    @Cacheable(cacheNames = "tennis:rankings", key = "#surface + ':' + #limit")
    public List<TennisRankingDto> rankings(String surface, int limit) {
        return tennisRepository.findRankings(surface, RANKINGS_MIN_MATCHES, limit);
    }

    @Cacheable(cacheNames = "tennis:accuracy", key = "#surface")
    public TennisAccuracyDto accuracy(String surface) {
        return tennisRepository.findAccuracy(surface);
    }
}
