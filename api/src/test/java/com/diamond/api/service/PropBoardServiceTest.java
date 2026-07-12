package com.diamond.api.service;

import com.diamond.api.dto.PitcherPropPickDto;
import com.diamond.api.dto.PropBoardPickDto;
import com.diamond.api.dto.PropBoardResponse;
import com.diamond.api.repository.ClearRateRepository;
import com.diamond.api.repository.ClearRateRepository.ClearRates;
import com.diamond.api.repository.PropBoardRepository;
import com.diamond.api.repository.PropBoardRepository.PitcherRow;
import com.diamond.api.repository.PropBoardRepository.SlateRow;
import org.junit.jupiter.api.BeforeEach;
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

    private final ClearRateRepository clearRates = mock(ClearRateRepository.class);

    /** No player has a demonstrated clear rate unless a test says so — the blend then
     *  regresses toward the league rate rather than NPE-ing on an unstubbed mock. */
    @BeforeEach
    void noClearRatesByDefault() {
        when(clearRates.findClearRatesBatch(any(), any())).thenReturn(Map.of());
    }

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
        PropBoardRepository repo = mockRepo(date);
        // One batter with only a walk probability set — the hrr/hr/tb markets see null
        // probs and produce no picks, isolating the bb market.
        SlateRow walker = slateRow(101, "Patient Pat", 0.46);
        when(repo.findSlateRows(date)).thenReturn(List.of(walker));
        when(clearRates.findClearRatesBatch(any(), any())).thenReturn(Map.of(
            // Only the walk rate is demonstrated.
            101, new ClearRates(null, null, null, 0.40, null, null,
                                 null, null, null, 0.42, null, null, 60, 0)));

        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        assertThat(resp.picks()).hasSize(1);
        PropBoardPickDto pick = resp.picks().get(0);
        assertThat(pick.market()).isEqualTo("bb");
        assertThat(pick.playerId()).isEqualTo(101);
        // The blend pulls the 0.46 model prob toward the 0.42 demonstrated walk rate.
        assertThat(pick.prob()).isBetween(0.30, 0.46);
    }

    @Test
    void board_surfacesTbAndHrrPicks_fromSimHistograms() {
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mockRepo(date);
        // 1000-sim histograms: P(TB >= 2) = 500/1000, P(H+R+RBI >= 2) = 700/1000.
        SlateRow slugger = simSlateRow(202, "Sim Slugger",
            new int[]{300, 200, 250, 150, 100}, new int[]{150, 150, 300, 250, 150});
        when(repo.findSlateRows(date)).thenReturn(List.of(slugger));
        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        // The same batter can't take two cards (used-set dedupe): hrr ranks first,
        // so tb has no eligible candidate left.
        assertThat(resp.picks()).extracting(PropBoardPickDto::market).containsExactly("hrr");
        PropBoardPickDto hrr = resp.picks().get(0);
        assertThat(hrr.line()).isEqualTo(1.5);
        assertThat(hrr.probModel()).isEqualTo(0.7);   // 700/1000 over 1.5
        // No season history: the blend regresses toward the 0.44 league rate.
        assertThat(hrr.prob()).isBetween(0.44, 0.7);
    }

    @Test
    void board_tbCard_dropsBattersWithoutSimRow() {
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mockRepo(date);
        // No sim histograms at all → tb/hrr probs are null → no tb/hrr cards (never a 0%).
        SlateRow walker = slateRow(101, "Patient Pat", 0.46);
        when(repo.findSlateRows(date)).thenReturn(List.of(walker));
        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        assertThat(resp.picks()).extracting(PropBoardPickDto::market).containsExactly("bb");
    }

    @Test
    void board_pitcherPickCarriesReasoningDrivers() {
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mockRepo(date);
        when(repo.findPitcherRows(date)).thenReturn(List.of(pitcherRow()));
        // A card only exists with a beatable line: over-lean at the fairly-quoted 5.5.
        when(repo.findPitcherMarketQuotes(date, "pitcher_k")).thenReturn(Map.of(
            new PropBoardRepository.PitcherQuoteKey(1L, 55),
            new PropBoardRepository.PitcherQuotes(5.5, 0.48, 0.56,
                new PropBoardRepository.PitcherPrice(5.5, "fanduel", 120, 2.20),
                new PropBoardRepository.PitcherPrice(5.5, "fanduel", -140, 1.71))));

        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        assertThat(resp.pitcherPicks()).isNotEmpty();
        PitcherPropPickDto k = resp.pitcherPicks().stream()
            .filter(p -> p.market().equals("pitcher_k")).findFirst().orElseThrow();
        assertThat(k.pitcherKRate()).isEqualTo(0.28);
        assertThat(k.pitcherBbRate()).isEqualTo(0.07);
        assertThat(k.pitcherXwobaAgainst()).isEqualTo(0.30);
        assertThat(k.pitcherHrPerPa()).isEqualTo(0.03);
        assertThat(k.opponentKRate()).isEqualTo(0.24);
        assertThat(k.opponentXwoba()).isEqualTo(0.31);
        assertThat(k.arsenal()).singleElement()
            .extracting(PitcherPropPickDto.ArsenalPitch::pitchType).isEqualTo("SL");
        // model P(over 5.5)=0.52 vs de-vigged 0.48/(0.48+0.56)≈0.4615 → over edge.
        assertThat(k.rankedBy()).isEqualTo("edge");
        assertThat(k.bestSide()).isEqualTo("over");
        assertThat(k.bestLine()).isEqualTo(5.5);
        assertThat(k.bestProb()).isEqualTo(0.52);
    }

    @Test
    void board_pitcherWidenedLadder_pricesOffOldGridLine() {
        // A 5.0 book line: not one of the fixed 4.5/5.5/6.5 display thresholds the old
        // 3-column read carried, but inside the workload ladder's range → the model now
        // INTERPOLATES P(over 5.0) rather than dropping the starter. Pre-change this
        // produced no edge candidate at all.
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mockRepo(date);
        when(repo.findPitcherRows(date)).thenReturn(List.of(pitcherRow()));
        when(repo.findPitcherMarketQuotes(date, "pitcher_k")).thenReturn(Map.of(
            new PropBoardRepository.PitcherQuoteKey(1L, 55),
            new PropBoardRepository.PitcherQuotes(5.0, 0.50, 0.50,
                new PropBoardRepository.PitcherPrice(5.0, "fanduel", -110, 1.91),
                new PropBoardRepository.PitcherPrice(5.0, "fanduel", -110, 1.91))));

        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        PitcherPropPickDto k = resp.pitcherPicks().stream()
            .filter(p -> p.market().equals("pitcher_k")).findFirst().orElseThrow();
        assertThat(k.rankedBy()).isEqualTo("edge");
        assertThat(k.bestLine()).isEqualTo(5.0);
        // P(over 5.0) interpolates between 4.5→0.71 and 5.5→0.52 = 0.615; fair = 0.50 →
        // over edge 0.115, bestProb 0.615.
        assertThat(k.bestSide()).isEqualTo("over");
        assertThat(k.bestProb()).isEqualTo(0.615);
        assertThat(k.edge()).isEqualTo(0.115);
    }

    @Test
    void board_pitcherBestPick_leansUnderForSoftTosser() {
        // A back-end starter modeled below a fairly-priced line: the edge points UNDER.
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mockRepo(date);
        when(repo.findPitcherRows(date)).thenReturn(List.of(softTosserRow()));
        when(repo.findPitcherMarketQuotes(date, "pitcher_k")).thenReturn(Map.of(
            new PropBoardRepository.PitcherQuoteKey(2L, 56),
            new PropBoardRepository.PitcherQuotes(4.5, 0.50, 0.50,
                new PropBoardRepository.PitcherPrice(4.5, "fanduel", -110, 1.91),
                new PropBoardRepository.PitcherPrice(4.5, "fanduel", -110, 1.91))));

        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        PitcherPropPickDto k = resp.pitcherPicks().stream()
            .filter(p -> p.market().equals("pitcher_k")).findFirst().orElseThrow();
        // model P(over 4.5)=0.40 < de-vigged 0.50 → under, bestProb = 1 - 0.40 = 0.60.
        assertThat(k.rankedBy()).isEqualTo("edge");
        assertThat(k.bestSide()).isEqualTo("under");
        assertThat(k.bestLine()).isEqualTo(4.5);
        assertThat(k.bestProb()).isEqualTo(0.60);
    }

    @Test
    void board_pitcherEdgeRanking_picksBiggestDisparity() {
        // The ace projects more Ks, but the SOFT TOSSER holds the bigger model-vs-line
        // gap: model P(over 4.5)=0.40 vs de-vigged 0.60 → 20pt under edge. The ace's
        // 5.5 line is fairly priced (0.52 vs 0.50 → 2pt). Disparity ranking must pick the
        // soft tosser's under, not the higher-projection ace.
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mockRepo(date);
        when(repo.findPitcherRows(date)).thenReturn(List.of(pitcherRow(), softTosserRow()));
        when(repo.findPitcherMarketQuotes(date, "pitcher_k")).thenReturn(Map.of(
            new PropBoardRepository.PitcherQuoteKey(1L, 55),
            new PropBoardRepository.PitcherQuotes(5.5, 0.52, 0.52,
                new PropBoardRepository.PitcherPrice(5.5, "fanduel", -110, 1.91),
                new PropBoardRepository.PitcherPrice(5.5, "fanduel", -110, 1.91)),
            new PropBoardRepository.PitcherQuoteKey(2L, 56),
            new PropBoardRepository.PitcherQuotes(4.5, 0.62, 0.42,
                new PropBoardRepository.PitcherPrice(4.5, "draftkings", -160, 1.63),
                new PropBoardRepository.PitcherPrice(4.5, "draftkings", 135, 2.35))));

        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        PitcherPropPickDto k = resp.pitcherPicks().stream()
            .filter(p -> p.market().equals("pitcher_k")).findFirst().orElseThrow();
        assertThat(k.rankedBy()).isEqualTo("edge");
        assertThat(k.pitcherId()).isEqualTo(56);          // soft tosser, not the ace
        assertThat(k.bestSide()).isEqualTo("under");      // edge points under
        assertThat(k.bestLine()).isEqualTo(4.5);          // the book's consensus line
        assertThat(k.bestProb()).isEqualTo(0.60);         // model P(under 4.5)
        // fair P(over) = 0.62/(0.62+0.42) ≈ 0.5962; edge = |0.40 − 0.5962| ≈ 0.1962.
        assertThat(k.edge()).isEqualTo(0.1962);
        assertThat(k.fairProb()).isEqualTo(0.4038);       // de-vigged P(under)
        assertThat(k.bestBook()).isEqualTo("draftkings"); // priced on the under side
        assertThat(k.priceAmerican()).isEqualTo(135);
        // EV = 0.60 × 2.35 − 1 = 0.41.
        assertThat(k.evPct()).isEqualTo(0.41);
        // The fairly-priced ace is the runner-up, carrying its own (tiny) edge and side.
        assertThat(k.runnersUp()).singleElement().satisfies(r -> {
            assertThat(r.pitcherId()).isEqualTo(55);
            assertThat(r.bestSide()).isEqualTo("over");   // 0.52 model vs 0.50 fair
            assertThat(r.edge()).isEqualTo(0.02);
        });
    }

    @Test
    void board_omitsPitcherCard_whenBookLineOffLadder() {
        // A 3.5 K line below the workload ladder's range → the model can't price it → no
        // edge candidate → no card at all (not a projection-ranked pick).
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mockRepo(date);
        when(repo.findPitcherRows(date)).thenReturn(List.of(pitcherRow()));
        when(repo.findPitcherMarketQuotes(date, "pitcher_k")).thenReturn(Map.of(
            new PropBoardRepository.PitcherQuoteKey(1L, 55),
            new PropBoardRepository.PitcherQuotes(3.5, 0.70, 0.34,
                new PropBoardRepository.PitcherPrice(3.5, "fanduel", -230, 1.43),
                new PropBoardRepository.PitcherPrice(3.5, "fanduel", 185, 2.85))));

        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        assertThat(resp.pitcherPicks()).extracting(PitcherPropPickDto::market)
            .doesNotContain("pitcher_k");
    }

    @Test
    void board_omitsPitcherCard_whenOneSidedQuote() {
        // One-sided quotes can't be de-vigged → no beatable line → no card.
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mockRepo(date);
        when(repo.findPitcherRows(date)).thenReturn(List.of(pitcherRow()));
        when(repo.findPitcherMarketQuotes(date, "pitcher_k")).thenReturn(Map.of(
            new PropBoardRepository.PitcherQuoteKey(1L, 55),
            new PropBoardRepository.PitcherQuotes(5.5, 0.52, null,
                new PropBoardRepository.PitcherPrice(5.5, "fanduel", -110, 1.91), null)));

        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        assertThat(resp.pitcherPicks()).extracting(PitcherPropPickDto::market)
            .doesNotContain("pitcher_k");
    }

    @Test
    void board_omitsPitcherCard_whenNoOddsAtAll() {
        // No quotes for any market → nothing beatable → no pitcher cards (never a
        // projection-magnitude pick masquerading as an edge).
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mockRepo(date);
        when(repo.findPitcherRows(date)).thenReturn(List.of(pitcherRow(), softTosserRow()));

        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        assertThat(resp.pitcherPicks()).isEmpty();
    }

    @Test
    void board_omitsPitcherCards_whenWorkloadDistributionAbsent() {
        // No pitcher_starts history → the workload model never ran → p_k/p_outs cols are
        // null and there's no sim histogram. A missing distribution must NOT surface as a
        // confident 100%-under pick: the card is dropped entirely.
        LocalDate date = LocalDate.of(2026, 6, 18);
        PropBoardRepository repo = mockRepo(date);
        when(repo.findPitcherRows(date)).thenReturn(List.of(noWorkloadRow()));

        PropBoardResponse resp = new PropBoardService(repo, clearRates).board(date);

        assertThat(resp.pitcherPicks()).isEmpty();
    }

    /** A repo mock with the no-data defaults every board test starts from. */
    private static PropBoardRepository mockRepo(LocalDate date) {
        PropBoardRepository repo = mock(PropBoardRepository.class);
        when(repo.findSlateRows(date)).thenReturn(List.of());
        when(repo.findPitcherRows(date)).thenReturn(List.of());
        when(repo.findBestOverPrice(any(), anyInt(), anyString())).thenReturn(null);
        when(repo.findBatterLinePrice(any(), anyInt(), anyString())).thenReturn(null);
        when(repo.findPitcherPrice(anyLong(), anyInt(), anyString(), anyString())).thenReturn(null);
        when(repo.findPitcherMarketQuotes(any(), anyString())).thenReturn(Map.of());
        return repo;
    }

    /** A starter with expected volumes but no distribution at all (workload null, no sim). */
    private static PitcherRow noWorkloadRow() {
        return new PitcherRow(
            3L, "AWY @ HOM",
            57, "No Workload", "HOM", "AWY",
            6.0, 16.0, 5.5,
            null, null,              // p_k / p_outs ladders null (workload never computed)
            null, null, null, new int[0], new int[0],  // no sim histograms
            0.25, 0.08, 0.32, 0.03, 0.22, 0.32,
            List.of(new PitcherPropPickDto.ArsenalPitch("FF", 0.50, 0.20, 94.0)));
    }

    /** A slate row with only the walk probability populated (other markets null). */
    private static SlateRow slateRow(int playerId, String name, double pBb1) {
        return new SlateRow(
            1L, "AWY @ HOM",
            playerId, name, "HOM",
            2, true, 4.3,
            null, null, null, pBb1,
            null, null, null,
            null, null, null, new int[0], new int[0],   // no sim tb/hrr distributions
            1.0, 1.0, null, null,
            1.0,
            null, null, "league_avg",
            null, "Some Pitcher", "Some Park",
            "R",
            null, null, null, null,
            null, null, null,
            null,         // hrDistanceFt
            0.10, 0.22);  // oppPitcherBbRate, oppPitcherKRate
    }

    /** A slate row carrying only the simulator's tb/hrr histograms (1000 sims). */
    private static SlateRow simSlateRow(int playerId, String name, int[] tbHist, int[] hrrHist) {
        return new SlateRow(
            1L, "AWY @ HOM",
            playerId, name, "HOM",
            3, true, 4.5,
            null, null, null, null,
            null, null, null,
            1000, 1.8, 2.4, tbHist, hrrHist,
            1.0, 1.0, null, 1.0,
            1.0,
            null, null, "league_avg",
            null, "Some Pitcher", "Some Park",
            "R",
            null, null, null, null,
            null, null, null,
            null,
            0.10, 0.22);
    }

    private static PitcherRow pitcherRow() {
        return new PitcherRow(
            1L, "AWY @ HOM",
            55, "Ace Arm", "HOM", "AWY",
            6.0, 16.0, 5.5,
            Map.of("4.5", 0.71, "5.5", 0.52, "6.5", 0.31),   // p_k ladder
            Map.of("14.5", 0.62, "17.5", 0.38),              // p_outs ladder
            null, null, null, new int[0], new int[0],
            0.28, 0.07, 0.30, 0.03, 0.24, 0.31,
            List.of(new PitcherPropPickDto.ArsenalPitch("SL", 0.38, 0.33, 86.2)));
    }

    /** A back-end starter projected under the low K line — used to exercise the under edge. */
    private static PitcherRow softTosserRow() {
        return new PitcherRow(
            2L, "AWY @ HOM",
            56, "Soft Toss", "HOM", "AWY",
            4.0, 14.0, 4.5,
            Map.of("4.5", 0.40, "5.5", 0.20, "6.5", 0.08),   // p_k ladder
            Map.of("14.5", 0.45, "17.5", 0.20),              // p_outs ladder
            null, null, null, new int[0], new int[0],
            0.18, 0.09, 0.34, 0.04, 0.20, 0.33,
            List.of(new PitcherPropPickDto.ArsenalPitch("CH", 0.30, 0.22, 82.0)));
    }
}
