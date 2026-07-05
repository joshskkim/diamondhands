package com.diamond.api.service;

import com.diamond.api.dto.BoomPickDto;
import com.diamond.api.repository.LottoRepository;
import com.diamond.api.repository.LottoRepository.CandidateRow;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Unit tests for the boom-score selection: a cold bottom-of-order slugger in a HR-friendly
 * spot outranks a milder candidate, while the not-cold / low-power / hostile-conditions rows
 * are screened out. The selection is age-blind by construction — {@link CandidateRow} carries
 * no birth date / age for the score to read.
 */
class LottoServiceTest {

    private static final LocalDate DATE = LocalDate.of(2026, 6, 30);

    @Test
    void picksHighestBoomScoreAmongEligibleSluggers() {
        LottoRepository repo = mock(LottoRepository.class);
        when(repo.findCandidates(DATE)).thenReturn(List.of(
            milderColdBat(),        // eligible but lower score
            coldParkFriendlySlugger(), // the winner
            notColdEnough(),        // screened: recent ≈ season
            weakPower()));          // screened: below league-average pop

        BoomPickDto pick = new LottoService(repo).lottoOfTheDay(DATE);

        assertThat(pick).isNotNull();
        assertThat(pick.playerId()).isEqualTo(701);
        assertThat(pick.lineupPosition()).isEqualTo(7);
        assertThat(pick.coldGap()).isCloseTo(0.060, org.assertj.core.data.Offset.offset(1e-9));
        assertThat(pick.condBoost()).isCloseTo(1.10 * 1.10 * 1.05, org.assertj.core.data.Offset.offset(1e-9));
        // powerBoost·condBoost·coldFactor = 1.56832… · 1.2705 · 1.30
        assertThat(pick.boomScore()).isCloseTo(2.5905, org.assertj.core.data.Offset.offset(1e-3));
        assertThat(pick.reasons()).isNotEmpty();
        // Best HR-over price passes through for the payout/grade.
        assertThat(pick.priceAmerican()).isEqualTo(650);
        assertThat(pick.bestBook()).isEqualTo("fanatics");
    }

    @Test
    void returnsNullWhenNothingIsColdAndPowerful() {
        LottoRepository repo = mock(LottoRepository.class);
        when(repo.findCandidates(DATE)).thenReturn(List.of(notColdEnough(), weakPower()));
        assertThat(new LottoService(repo).lottoOfTheDay(DATE)).isNull();
    }

    @Test
    void screensOutHostileHrConditions() {
        // Cold and powerful, but park·pitcher·weather actively suppress HRs today (< COND_MIN).
        LottoRepository repo = mock(LottoRepository.class);
        when(repo.findCandidates(DATE)).thenReturn(List.of(coldSluggerInPitchersPark()));
        assertThat(new LottoService(repo).lottoOfTheDay(DATE)).isNull();
    }

    @Test
    void returnsNullOnEmptySlate() {
        LottoRepository repo = mock(LottoRepository.class);
        when(repo.findCandidates(DATE)).thenReturn(List.of());
        assertThat(new LottoService(repo).lottoOfTheDay(DATE)).isNull();
    }

    // ── fixtures (all already satisfy the repo's SQL screen: bottom order, non-null form) ──

    private static CandidateRow coldParkFriendlySlugger() {
        return new CandidateRow(
            1L, 701, "Cold Slugger", "R", true, 7, "Some Ace", "HOM", "AWY",
            0.12, 0.12, 0.250, 0.180, 0.340, 0.280, 45,
            1.10, 1.10, 1.05, null,
            650, 7.5, "fanatics");
    }

    private static CandidateRow milderColdBat() {
        return new CandidateRow(
            1L, 702, "Mild Bat", "L", false, 8, "Some Ace", "HOM", "AWY",
            0.09, 0.09, 0.180, 0.150, 0.320, 0.300, 40,
            1.0, 1.0, 1.0, null,
            500, 6.0, "fanduel");
    }

    private static CandidateRow notColdEnough() {
        // recent ≈ season → coldGap below COLD_MIN.
        return new CandidateRow(
            2L, 703, "Hot Bat", "R", true, 6, "Some Ace", "HOM", "AWY",
            0.11, 0.11, 0.230, 0.225, 0.330, 0.327, 50,
            1.10, 1.10, 1.05, null,
            700, 8.0, "draftkings");
    }

    private static CandidateRow weakPower() {
        // Cold, but no real pop → powerBoost below POWER_MIN.
        return new CandidateRow(
            3L, 704, "Slap Hitter", "L", false, 9, "Some Ace", "HOM", "AWY",
            0.05, 0.05, 0.100, 0.060, 0.320, 0.270, 35,
            1.10, 1.10, 1.05, null,
            900, 10.0, "fanduel");
    }

    private static CandidateRow coldSluggerInPitchersPark() {
        return new CandidateRow(
            4L, 705, "Trapped Slugger", "R", true, 7, "Some Ace", "HOM", "AWY",
            0.12, 0.12, 0.250, 0.180, 0.340, 0.280, 45,
            0.90, 0.90, 1.00, null,   // condBoost = 0.81 < COND_MIN
            600, 7.0, "fanatics");
    }
}
