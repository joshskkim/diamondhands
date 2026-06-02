package com.diamond.api.service;

import com.diamond.api.dto.BatterProjectionDto;
import com.diamond.api.dto.BatterVsArsenalDto;
import com.diamond.api.dto.GameProjectionsResponse;
import com.diamond.api.dto.PitchArsenalDto;
import com.diamond.api.dto.TeamBattersDto;
import com.diamond.api.repository.PitchRepository;
import com.diamond.api.repository.ProjectionRepository;
import com.diamond.api.repository.ProjectionRepository.BatterRow;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class ProjectionService {

    private final ProjectionRepository projectionRepository;
    private final PitchRepository pitchRepository;

    public ProjectionService(ProjectionRepository projectionRepository, PitchRepository pitchRepository) {
        this.projectionRepository = projectionRepository;
        this.pitchRepository = pitchRepository;
    }

    @Cacheable(cacheNames = "projections", key = "#gameId")
    public GameProjectionsResponse gameProjections(long gameId) {
        List<BatterRow> rows = projectionRepository.findByGameId(gameId);
        if (rows.isEmpty()) {
            return new GameProjectionsResponse(
                gameId,
                new TeamBattersDto(null, false, List.of()),
                new TeamBattersDto(null, false, List.of()));
        }

        String homeAbbr = rows.get(0).homeAbbr();
        String awayAbbr = rows.get(0).awayAbbr();

        List<BatterProjectionDto> homeBatters = new ArrayList<>();
        List<BatterProjectionDto> awayBatters = new ArrayList<>();
        boolean homeConfirmed = false;
        boolean awayConfirmed = false;

        for (BatterRow row : rows) {
            boolean confirmed = Boolean.TRUE.equals(row.projection().lineupConfirmed());
            BatterProjectionDto enriched = withArsenal(row);
            if (row.isHome()) {
                homeBatters.add(enriched);
                homeConfirmed |= confirmed;
            } else {
                awayBatters.add(enriched);
                awayConfirmed |= confirmed;
            }
        }

        return new GameProjectionsResponse(
            gameId,
            new TeamBattersDto(homeAbbr, homeConfirmed, homeBatters),
            new TeamBattersDto(awayAbbr, awayConfirmed, awayBatters));
    }

    /** Attach the opposing pitcher's arsenal and the batter's regressed xwOBA per pitch type. */
    private BatterProjectionDto withArsenal(BatterRow row) {
        BatterProjectionDto p = row.projection();
        String pitcherHand = p.opposingPitcher().throws_();
        LocalDate asOf = row.gameDate();
        if (pitcherHand == null || asOf == null) {
            return p;
        }
        int pitcherId = p.opposingPitcher().id();
        int batterId = p.player().id();
        String batterHand = effectiveHand(p.player().bats(), pitcherHand);

        List<PitchArsenalDto> arsenal = pitchRepository.arsenal(pitcherId, pitcherHand, batterHand, asOf);
        Map<String, PitchRepository.BatterPitchRow> byType = pitchRepository
            .batterPitchStats(batterId, pitcherHand, asOf).stream()
            .collect(Collectors.toMap(PitchRepository.BatterPitchRow::pitchType, Function.identity(), (a, b) -> a));

        List<BatterVsArsenalDto> vsArsenal = new ArrayList<>();
        for (PitchArsenalDto a : arsenal) {  // arsenal is already sorted by usage desc
            PitchRepository.BatterPitchRow bs = byType.get(a.pitchType());
            if (bs == null) {
                continue;
            }
            Double regressed = PitchRepository.regress(
                bs.rawXwoba(), bs.pitchesSeen(), bs.leagueXwoba(), PitchRepository.REGRESSION_K_PITCHES_BATTER);
            Double edge = (regressed != null && bs.leagueXwoba() != null) ? regressed - bs.leagueXwoba() : null;
            vsArsenal.add(new BatterVsArsenalDto(
                a.pitchType(), round4(regressed), bs.pitchesSeen(), formatEdge(edge)));
        }

        return new BatterProjectionDto(
            p.player(), p.opposingPitcher(), p.expectedPa(), p.probabilities(),
            p.expectedHits(), p.expectedTotalBases(), p.adjustments(), p.pitcherDataQuality(),
            p.lineupPosition(), p.lineupConfirmed(), p.matchupXwoba(), p.matchupQuality(),
            arsenal, vsArsenal);
    }

    /** Switch hitters bat opposite the pitcher's throwing hand. */
    static String effectiveHand(String bats, String pitcherThrows) {
        if ("S".equals(bats)) {
            return "R".equals(pitcherThrows) ? "L" : "R";
        }
        return ("L".equals(bats) || "R".equals(bats)) ? bats : "R";
    }

    static String formatEdge(Double edge) {
        return edge == null ? null : String.format("%+.3f", edge);
    }

    private static Double round4(Double v) {
        return v == null ? null : Math.round(v * 10000.0) / 10000.0;
    }
}
