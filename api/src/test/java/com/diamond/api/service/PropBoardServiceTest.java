package com.diamond.api.service;

import com.diamond.api.dto.PitcherPropPickDto;
import com.diamond.api.dto.PropBoardPickDto;
import com.diamond.api.dto.PropBoardResponse;
import com.diamond.api.repository.PropBoardRepository;
import com.diamond.api.repository.PropBoardRepository.ClearRates;
import com.diamond.api.repository.PropBoardRepository.PitcherRow;
import com.diamond.api.repository.PropBoardRepository.SlateRow;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Unit tests for the prop board's sim-blend math (the pure helper that mixes the
 * Monte-Carlo simulator's per-batter estimate into the closed-form model probability)
 * plus the board assembly for the walks market and pitcher reasoning drivers.
 */
class PropBoardServiceTest {

    private static final double EPS = 1e-9;

    @Test
    void simBlend_returnsModelProb_whenSimMissing() {
        // Padded lineup slots have no sim estimate — must fall back to the closed form.
        assertThat(PropBoardService.simBlend(0.62, null, 0.5)).isCloseTo(0.62, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void simBlend_returnsModelProb_whenWeightZero() {
        // Default (unfit) weight is 0 → board behaves exactly as before the blend existed.
        assertThat(PropBoardService.simBlend(0.62, 0.40, 0.0)).isCloseTo(0.62, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void simBlend_returnsModelProb_whenWeightNegative() {
        assertThat(PropBoardService.simBlend(0.62, 0.40, -0.3)).isCloseTo(0.62, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void simBlend_weightsTowardSim() {
        // 0.25 weight pulls a 0.60 model prob a quarter of the way to the sim's 0.40.
        assertThat(PropBoardService.simBlend(0.60, 0.40, 0.25))
            .isCloseTo(0.55, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void simBlend_fullWeightReturnsSim() {
        assertThat(PropBoardService.simBlend(0.60, 0.40, 1.0))
            .isCloseTo(0.40, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void board_surfacesWalksPick_routingToWalkClearRate() {
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mock(PropBoardRepository.class);
        // One batter with only a walk probability set — the hit/hr/k markets see null
        // probs and produce no picks, isolating the new bb market.
        SlateRow walker = slateRow(101, "Patient Pat", 0.46);
        when(repo.findSlateRows(date)).thenReturn(List.of(walker));
        when(repo.findClearRatesBatch(any(), any())).thenReturn(Map.of(
            // hit/hr/k season rates null; only the walk rate is demonstrated.
            101, new ClearRates(null, null, null, 0.40,
                                 null, null, null, 0.42, 60)));
        when(repo.findPitcherRows(date)).thenReturn(List.of());
        when(repo.findBestOverPrice(any(), anyInt(), anyString())).thenReturn(null);

        PropBoardResponse resp = new PropBoardService(repo).board(date);

        assertThat(resp.picks()).hasSize(1);
        PropBoardPickDto pick = resp.picks().get(0);
        assertThat(pick.market()).isEqualTo("bb");
        assertThat(pick.playerId()).isEqualTo(101);
        // The blend pulls the 0.46 model prob toward the 0.42 demonstrated walk rate.
        assertThat(pick.prob()).isBetween(0.30, 0.46);
    }

    @Test
    void board_pitcherPickCarriesReasoningDrivers() {
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mock(PropBoardRepository.class);
        when(repo.findSlateRows(date)).thenReturn(List.of());
        when(repo.findClearRatesBatch(any(), any())).thenReturn(Map.of());
        when(repo.findPitcherRows(date)).thenReturn(List.of(pitcherRow()));
        when(repo.findPitcherOverPrice(anyLong(), anyInt(), anyString())).thenReturn(null);

        PropBoardResponse resp = new PropBoardService(repo).board(date);

        assertThat(resp.pitcherPicks()).isNotEmpty();
        PitcherPropPickDto k = resp.pitcherPicks().stream()
            .filter(p -> p.market().equals("pitcher_k")).findFirst().orElseThrow();
        assertThat(k.pitcherKRate()).isEqualTo(0.28);
        assertThat(k.opponentKRate()).isEqualTo(0.24);
        assertThat(k.opponentXwoba()).isEqualTo(0.31);
    }

    /** A slate row with only the walk probability populated (other markets null). */
    private static SlateRow slateRow(int playerId, String name, double pBb1) {
        return new SlateRow(
            1L, "AWY @ HOM",
            playerId, name, "HOM",
            2, true, 4.3,
            null, null, null, pBb1,
            null, null, null,
            1.0, 1.0, null, null,
            1.0,
            null, null, "league_avg",
            null, "Some Pitcher", "Some Park",
            "R",
            null, null, null, null,
            null, null, null);
    }

    private static PitcherRow pitcherRow() {
        return new PitcherRow(
            1L, "AWY @ HOM",
            55, "Ace Arm", "HOM", "AWY",
            6.0, 16.0, 5.5,
            0.71, 0.52, 0.31,
            0.62, 0.38,
            null, null, null, new int[0], new int[0],
            0.28, 0.24, 0.31);
    }
}
