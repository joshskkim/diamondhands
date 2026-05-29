package com.diamond.api.service;

import com.diamond.api.dto.BatterProjectionDto;
import com.diamond.api.dto.GameProjectionsResponse;
import com.diamond.api.dto.TeamBattersDto;
import com.diamond.api.repository.ProjectionRepository;
import com.diamond.api.repository.ProjectionRepository.BatterRow;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class ProjectionService {

    private final ProjectionRepository projectionRepository;

    public ProjectionService(ProjectionRepository projectionRepository) {
        this.projectionRepository = projectionRepository;
    }

    @Cacheable(cacheNames = "projections", key = "#gameId")
    public GameProjectionsResponse gameProjections(long gameId) {
        List<BatterRow> rows = projectionRepository.findByGameId(gameId);
        if (rows.isEmpty()) {
            return new GameProjectionsResponse(gameId, new TeamBattersDto(null, List.of()), new TeamBattersDto(null, List.of()));
        }

        String homeAbbr = rows.get(0).homeAbbr();
        String awayAbbr = rows.get(0).awayAbbr();

        List<BatterProjectionDto> homeBatters = new ArrayList<>();
        List<BatterProjectionDto> awayBatters = new ArrayList<>();

        for (BatterRow row : rows) {
            if (row.isHome()) {
                homeBatters.add(row.projection());
            } else {
                awayBatters.add(row.projection());
            }
        }

        return new GameProjectionsResponse(
            gameId,
            new TeamBattersDto(homeAbbr, homeBatters),
            new TeamBattersDto(awayAbbr, awayBatters));
    }
}
