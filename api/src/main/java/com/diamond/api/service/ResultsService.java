package com.diamond.api.service;

import com.diamond.api.dto.PlayerResultsResponse;
import com.diamond.api.repository.ResultsRepository;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;

/** Per-player actual results for a slate; read-only and cached per date. */
@Service
public class ResultsService {

    private final ResultsRepository repo;

    public ResultsService(ResultsRepository repo) {
        this.repo = repo;
    }

    @Cacheable(cacheNames = "playerResults", key = "#date.toString()")
    public PlayerResultsResponse playerResults(LocalDate date) {
        return new PlayerResultsResponse(
            date.toString(), repo.findBatters(date), repo.findPitchers(date));
    }

    /** In-progress counts from player_game_live. Uncached — it must reflect the latest tick
     *  (the table is rewritten every ~30s while games are live) and the read is cheap. */
    public PlayerResultsResponse livePlayerResults(LocalDate date) {
        return new PlayerResultsResponse(
            date.toString(), repo.findLiveBatters(date), repo.findLivePitchers(date));
    }
}
