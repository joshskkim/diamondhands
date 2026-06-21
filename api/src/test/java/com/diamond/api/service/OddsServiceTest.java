package com.diamond.api.service;

import com.diamond.api.dto.BestPlayDto;
import com.diamond.api.repository.OddsRepository;
import com.diamond.api.repository.OddsRepository.GameMeta;
import com.diamond.api.repository.OddsRepository.GameOddRow;
import com.diamond.api.repository.OddsRepository.PropOddRow;
import com.diamond.api.repository.OddsRepository.RunProj;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Guards the "under at 100%" regression: a degenerate model probability of (effectively)
 * 0 or 1 — e.g. p_hit_1plus = 0 for a batter projected for 0 PA — must not surface as a
 * confident edge. Before the fix the opposite side read 1.0 - 0 = 1.0 and topped the board.
 */
class OddsServiceTest {

    private static final LocalDate SLATE = LocalDate.of(2026, 6, 21);
    private static final long GAME = 1L;

    private static PropOddRow prop(String side, double pHit1) {
        return new PropOddRow(
            100, "Test Batter", "R", "OF",
            "hit", side, 0.5, "FanDuel",
            100, 2.0, 0.5,
            pHit1, 0.0, 0.03);
    }

    private OddsService serviceWithProp(double pHit1) {
        OddsRepository repo = mock(OddsRepository.class);
        when(repo.findGameIdsWithOdds(SLATE)).thenReturn(List.of(GAME));
        when(repo.findGameOddsByDate(SLATE)).thenReturn(Map.<Long, List<GameOddRow>>of());
        when(repo.findPropOddsByDate(SLATE)).thenReturn(
            Map.of(GAME, List.of(prop("over", pHit1), prop("under", pHit1))));
        when(repo.findRunProjByDate(SLATE)).thenReturn(Map.<Long, RunProj>of());
        when(repo.findGameMetaByDate(SLATE)).thenReturn(Map.of(GAME, new GameMeta("AAA", "BBB")));
        return new OddsService(repo);
    }

    @Test
    void zeroProbBatter_doesNotSurfaceA100PercentUnder() {
        List<BestPlayDto> plays = serviceWithProp(0.0).bestPlays(SLATE);

        // The degenerate over (p=0) and its phantom 100% under are both dropped: no play
        // for this player, and certainly none with a model probability of 1.0.
        assertThat(plays).noneMatch(p -> p.modelProb() >= 1.0 - 1e-9);
        assertThat(plays).allMatch(p -> p.playerId() == null || p.playerId() != 100);
    }

    @Test
    void healthyProbBatter_stillSurfacesBothSides() {
        List<BestPlayDto> plays = serviceWithProp(0.6).bestPlays(SLATE);

        // A real projection (0.6 over → 0.4 under) is unaffected by the guard.
        assertThat(plays).anyMatch(p -> p.playerId() != null && p.playerId() == 100
            && p.side().equals("over") && Math.abs(p.modelProb() - 0.6) < 1e-9);
        assertThat(plays).anyMatch(p -> p.playerId() != null && p.playerId() == 100
            && p.side().equals("under") && Math.abs(p.modelProb() - 0.4) < 1e-9);
    }
}
