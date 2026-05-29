package com.diamond.api.service;

import com.diamond.api.dto.TodayGameDto;
import com.diamond.api.repository.GameRepository;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.List;

@Service
public class GameService {

    private final GameRepository gameRepository;

    public GameService(GameRepository gameRepository) {
        this.gameRepository = gameRepository;
    }

    @Cacheable(cacheNames = "games:today", key = "#date.toString()")
    public List<TodayGameDto> todayGames(LocalDate date) {
        return gameRepository.findByDate(date);
    }
}
