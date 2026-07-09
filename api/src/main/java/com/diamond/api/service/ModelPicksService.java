package com.diamond.api.service;

import com.diamond.api.dto.ModelPickResultDto;
import com.diamond.api.repository.ModelPicksRepository;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.List;

/**
 * Cached read of the recorded Model's Picks. The ingester's record-picks owns every
 * mutation (lock, budget, lineup re-eval); the old client-driven reconcile endpoint is
 * gone with the live-computed board, so cache staleness is bounded only by the Redis
 * TTL (~5 min) between cron writes.
 */
@Service
public class ModelPicksService {

    private final ModelPicksRepository repo;

    public ModelPicksService(ModelPicksRepository repo) {
        this.repo = repo;
    }

    @Cacheable(cacheNames = "modelPicks", key = "#date.toString()")
    public List<ModelPickResultDto> picks(LocalDate date) {
        return repo.findByDate(date);
    }
}
