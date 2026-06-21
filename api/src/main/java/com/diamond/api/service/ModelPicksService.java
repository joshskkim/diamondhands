package com.diamond.api.service;

import com.diamond.api.dto.ModelPickResultDto;
import com.diamond.api.repository.ModelPicksRepository;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.List;

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
