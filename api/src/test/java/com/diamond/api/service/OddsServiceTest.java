package com.diamond.api.service;

import com.diamond.api.dto.BestPlayDto;
import com.diamond.api.repository.ClearRateRepository;
import com.diamond.api.repository.ClearRateRepository.ClearRates;
import com.diamond.api.repository.OddsRepository;
import com.diamond.api.repository.OddsRepository.GameMeta;
import com.diamond.api.repository.OddsRepository.GameOddRow;
import com.diamond.api.repository.OddsRepository.PropModelRow;
import com.diamond.api.repository.OddsRepository.PropOddRow;
import com.diamond.api.repository.OddsRepository.RunProj;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Covers the prop-pricing path of the odds board: which markets carry a model probability
 * at which lines, where the clear-rate blend applies, and the "under at 100%" regression
 * (a degenerate model probability of effectively 0 or 1 — e.g. p_hit_1plus = 0 for a
 * batter projected for 0 PA — must not surface as a confident edge; before the fix the
 * opposite side read 1.0 - 0 = 1.0 and topped the board).
 */
class OddsServiceTest {

    private static final LocalDate SLATE = LocalDate.of(2026, 6, 21);
    private static final long GAME = 1L;
    private static final double EPS = 1e-9;

    private final OddsRepository repo = mock(OddsRepository.class);
    private final ClearRateRepository clearRates = mock(ClearRateRepository.class);

    /** No demonstrated clear rate unless a test provides one: the blend then regresses
     *  toward the league rate rather than NPE-ing on an unstubbed mock. */
    @BeforeEach
    void noClearRatesByDefault() {
        when(clearRates.findClearRatesBatch(any(), any())).thenReturn(Map.of());
        when(repo.findGameIdsWithOdds(SLATE)).thenReturn(List.of(GAME));
        when(repo.findGameOddsByDate(SLATE)).thenReturn(Map.<Long, List<GameOddRow>>of());
        when(repo.findRunProjByDate(SLATE)).thenReturn(Map.<Long, RunProj>of());
        when(repo.findGameMetaByDate(SLATE)).thenReturn(Map.of(GAME, new GameMeta("AAA", "BBB")));
    }

    // ── row builders ─────────────────────────────────────────────────────────

    /** A model row with nothing projected — the shape a scratched player produces. */
    private static PropModelRow emptyModel() {
        return new PropModelRow(null, null, null, null, null,
            null, new int[0], new int[0], null, null, null, new int[0], new int[0]);
    }

    /** A batter's SERVED hit prob — the pre-blended value the odds path reads for hit@0.5
     *  (the engine already applied the clear-rate blend; the API must not re-blend it). */
    private static PropModelRow hitModel(Double served) {
        return new PropModelRow(null, served, null, null, null,
            null, new int[0], new int[0], null, null, null, new int[0], new int[0]);
    }

    private static PropModelRow batterModel(Double pHr, Double pBb1) {
        return new PropModelRow(null, null, null, pHr, pBb1,
            null, new int[0], new int[0], null, null, null, new int[0], new int[0]);
    }

    /** 100 sims: `hist[i]` = sims in which the player recorded exactly i. */
    private static PropModelRow simBatterModel(int[] tbHist, int[] hrrHist) {
        return new PropModelRow(null, null, null, null, null,
            100, tbHist, hrrHist, null, null, null, new int[0], new int[0]);
    }

    private static PropModelRow pitcherModel(Map<String, Double> pK, Map<String, Double> pOuts) {
        return new PropModelRow(null, null, null, null, null,
            null, new int[0], new int[0], pK, pOuts, null, new int[0], new int[0]);
    }

    private static PropModelRow simPitcherModel(int[] hitsHist, int[] erHist) {
        return new PropModelRow(null, null, null, null, null,
            null, new int[0], new int[0], null, null, 100, hitsHist, erHist);
    }

    private static PropOddRow prop(String market, String side, double line, PropModelRow model) {
        return new PropOddRow(
            100, "Test Player", "R", "OF",
            market, side, line, "FanDuel",
            100, 2.0, 0.5,
            model);
    }

    /** Both sides quoted, so the market de-vigs and the play reaches the board. */
    private List<BestPlayDto> playsFor(String market, double line, PropModelRow model) {
        when(repo.findPropOddsByDate(SLATE)).thenReturn(Map.of(GAME, List.of(
            prop(market, "over", line, model), prop(market, "under", line, model))));
        return new OddsService(repo, clearRates).bestPlays(SLATE);
    }

    private static Double overProb(List<BestPlayDto> plays) {
        return plays.stream().filter(p -> "over".equals(p.side()))
            .map(BestPlayDto::modelProb).findFirst().orElse(null);
    }

    // ── the degenerate-probability guard ─────────────────────────────────────

    @Test
    void zeroServedHit_doesNotSurfaceA100PercentUnder() {
        // The engine writes NULL served for a degenerate batter, but defend at the API too:
        // a served 0 must be dropped by sane(), not surface its phantom 100% under.
        List<BestPlayDto> plays = playsFor("hit", 0.5, hitModel(0.0));

        assertThat(plays).noneMatch(p -> p.modelProb() >= 1.0 - 1e-9);
        assertThat(plays).allMatch(p -> p.playerId() == null || p.playerId() != 100);
    }

    @Test
    void nullServedHit_yieldsNoPlay() {
        // The engine's usual signal for "don't bet this batter's hit" — no served value.
        assertThat(playsFor("hit", 0.5, hitModel(null))).isEmpty();
    }

    @Test
    void noProjectionAtAll_yieldsNoPlay() {
        assertThat(playsFor("hit", 0.5, emptyModel())).isEmpty();
        assertThat(playsFor("tb", 1.5, emptyModel())).isEmpty();
        assertThat(playsFor("pitcher_k", 5.5, emptyModel())).isEmpty();
    }

    // ── which markets price, and at which lines ──────────────────────────────

    @Test
    void batterOccurrenceMarketsPriceAtTheirOwnLine() {
        assertThat(overProb(playsFor("hit", 0.5, hitModel(0.55)))).isNotNull();
        assertThat(overProb(playsFor("hr", 0.5, batterModel(0.12, null)))).isNotNull();
        assertThat(overProb(playsFor("bb", 0.5, batterModel(null, 0.28)))).isNotNull();
        // hr is a 1+ market: a book quoting 1.5 gets no model rather than a wrong one.
        assertThat(playsFor("hr", 1.5, batterModel(0.12, null))).isEmpty();
    }

    @Test
    void simHistogramMarketsPriceAnyHalfLine() {
        // 100 sims: 40 with 0 TB, 30 with 1, 30 with 2. P(over 1.5) = 30/100 raw. 1.5 IS the
        // tb canonical line, so it blends: no clear rate → empirical = league 0.31, w = 25/85
        // → 0.2941*0.31 + 0.7059*0.30 = 0.30294.
        int[] tb = {40, 30, 30};
        assertThat(overProb(playsFor("tb", 1.5, simBatterModel(tb, new int[0]))))
            .isCloseTo(0.30294, org.assertj.core.data.Offset.offset(1e-5));
        // P(over 0.5) = 60/100, an off-canonical line → unblended, so exactly 0.60.
        assertThat(overProb(playsFor("tb", 0.5, simBatterModel(tb, new int[0]))))
            .isCloseTo(0.60, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void pitcherLadderPricesOnGridAndNotOffIt() {
        Map<String, Double> pK = Map.of("4.5", 0.62, "5.5", 0.44, "6.5", 0.27);
        assertThat(overProb(playsFor("pitcher_k", 5.5, pitcherModel(pK, null))))
            .isCloseTo(0.44, org.assertj.core.data.Offset.offset(EPS));
        // A line the workload model never materialized can't be priced — no play, not a 0%.
        assertThat(playsFor("pitcher_k", 10.5, pitcherModel(pK, null))).isEmpty();
    }

    @Test
    void pitcherOutsPricesOffTheWidenedGrid() {
        // 15.5 was unpriceable before the workload grid widened past 14.5/17.5.
        Map<String, Double> pOuts = Map.of("14.5", 0.70, "15.5", 0.58, "17.5", 0.31);
        assertThat(overProb(playsFor("pitcher_outs", 15.5, pitcherModel(null, pOuts))))
            .isCloseTo(0.58, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void pitcherSimMarketsPriceOffHistograms() {
        // 100 sims: 50 with <=4 hits, 30 with 5, 20 with 6. P(over 4.5) = 50/100.
        int[] hits = {10, 10, 10, 10, 10, 30, 20};
        assertThat(overProb(playsFor("pitcher_hits_allowed", 4.5, simPitcherModel(hits, new int[0]))))
            .isCloseTo(0.50, org.assertj.core.data.Offset.offset(EPS));
        int[] er = {40, 30, 20, 10};
        assertThat(overProb(playsFor("pitcher_earned_runs", 1.5, simPitcherModel(new int[0], er))))
            .isCloseTo(0.30, org.assertj.core.data.Offset.offset(EPS));
    }

    // ── the blend, and its canonical-line rule ───────────────────────────────

    @Test
    void batterMarketBlendsTowardTheDemonstratedClearRate() {
        // HR still blends at serve time (only hit moved to the engine). A 60-game .20-HR
        // hitter, model 0.30: empirical = (60*.20 + 25*.15)/85 = .18529; w = 85/145 = .58621
        // → .58621*.18529 + .41379*.30 = .23278.
        when(clearRates.findClearRatesBatch(any(), any())).thenReturn(Map.of(
            100, new ClearRates(null, null, null, null, null, null,
                                null, 0.20, null, null, null, null, 60, 0)));

        assertThat(overProb(playsFor("hr", 0.5, batterModel(0.30, null))))
            .isCloseTo(0.23278, org.assertj.core.data.Offset.offset(1e-4));
    }

    @Test
    void servedHitIsNotReblended() {
        // The engine already blended hit into p_hit_1plus_served; the API must read it as-is,
        // even with a (batter-shaped) clear rate present — no double shrinkage.
        when(clearRates.findClearRatesBatch(any(), any())).thenReturn(Map.of(
            100, new ClearRates(null, null, null, null, null, null,
                                0.42, null, null, null, null, null, 60, 0)));

        assertThat(overProb(playsFor("hit", 0.5, hitModel(0.55))))
            .isCloseTo(0.55, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void hitAtOneAndAHalfUsesRawSecondHitProb() {
        // hit 1.5 reads the raw p_hit_2plus (never blended, never served) — unchanged.
        when(clearRates.findClearRatesBatch(any(), any())).thenReturn(Map.of(
            100, new ClearRates(null, null, null, null, null, null,
                                0.42, null, null, null, null, null, 60, 0)));
        PropModelRow twoHits = new PropModelRow(null, null, 0.30, null, null,
            null, new int[0], new int[0], null, null, null, new int[0], new int[0]);

        assertThat(overProb(playsFor("hit", 1.5, twoHits)))
            .isCloseTo(0.30, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void pitcherMarketsAreNeverBlended() {
        // There are no pitcher clear rates; the ladder probability must survive intact even
        // when the (batter-shaped) rates row happens to be populated for this player id.
        when(clearRates.findClearRatesBatch(any(), any())).thenReturn(Map.of(
            100, new ClearRates(null, null, null, null, null, null,
                                0.42, null, null, null, null, null, 60, 0)));

        assertThat(overProb(playsFor("pitcher_k", 5.5, pitcherModel(Map.of("5.5", 0.44), null))))
            .isCloseTo(0.44, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void healthyProbBatter_stillSurfacesBothSides() {
        List<BestPlayDto> plays = playsFor("hit", 0.5, hitModel(0.6));

        // A real projection is unaffected by the guard; over + under still sum to 1.
        double over = plays.stream().filter(p -> "over".equals(p.side()))
            .findFirst().orElseThrow().modelProb();
        double under = plays.stream().filter(p -> "under".equals(p.side()))
            .findFirst().orElseThrow().modelProb();
        assertThat(over + under).isCloseTo(1.0, org.assertj.core.data.Offset.offset(EPS));
        assertThat(over).isStrictlyBetween(0.0, 1.0);
    }
}
