package com.diamond.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.diamond.api.dto.GameTotalDto;
import com.diamond.api.dto.MostLikelyResponse;
import com.diamond.api.dto.RunLineDto;
import com.diamond.api.repository.MostLikelyRepository;
import com.diamond.api.repository.MostLikelyRepository.SimRow;
import java.time.LocalDate;
import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * The sim-board assembly math: totals lean labelling off the histogram, and the run-line's
 * two paths — de-vigged best-edge side when odds + the +1.5 column exist, favorite -1.5
 * fallback when they don't. These guard the exact orientation logic (which team lays -1.5,
 * whose cover prob is whose) that V69's pHomeCoverPlus15 column was added to fix.
 */
class MostLikelyServiceTest {

    private static final LocalDate DATE = LocalDate.of(2026, 7, 12);

    /** 100-sim total-runs histogram: index = total runs, value = sims. */
    private static final int[] HIST = new int[20];
    static {
        HIST[6] = 30; HIST[8] = 30; HIST[9] = 40;  // P(total > 8.5) = 0.40, P(> 7.5) = 0.70
    }

    private static SimRow row(Double bookTotal, Double favImplied, Double dogImplied,
                              String favSide, Double pHomeCoverPlus15) {
        return new SimRow(1L, "AWY @ HOM", "HOM", "AWY", 100,
            8.2, 0.55, HIST,
            0.42, 0.30,
            pHomeCoverPlus15,
            0.49, bookTotal, favImplied, dogImplied, favSide);
    }

    private MostLikelyResponse board(SimRow row) {
        MostLikelyRepository repo = mock(MostLikelyRepository.class);
        when(repo.findSimRows(DATE)).thenReturn(List.of(row));
        when(repo.findPropRows(DATE)).thenReturn(List.of());
        return new MostLikelyService(repo).board(DATE);
    }

    @Test
    void totals_edgeAndPOverComeFromTheHistogram() {
        GameTotalDto t = board(row(8.5, null, null, null, null)).totals().get(0);
        assertThat(t.edge()).isEqualTo(-0.3);       // 8.2 sim vs 8.5 line
        assertThat(t.pOver()).isEqualTo(0.40);      // 40 of 100 sims above 8.5
        assertThat(t.lean()).isEqualTo("under");    // edge < -0.05
    }

    @Test
    void totals_noBookLine_meansNoLeanNotAFakeOne() {
        GameTotalDto t = board(row(null, null, null, null, null)).totals().get(0);
        assertThat(t.bookLine()).isNull();
        assertThat(t.edge()).isNull();
        assertThat(t.lean()).isNull();
    }

    @Test
    void runLine_edgePath_recommendsTheDogWhenItsCoverBeatsTheFairPrice() {
        // Book lays HOM -1.5 at implied 0.60 (fav) / 0.44 (dog) → fair fav = 0.5769.
        // Sim says home covers -1.5 only 42% → dog (+1.5) side carries the edge.
        RunLineDto r = board(row(8.5, 0.60, 0.44, "home", 0.58)).runLine().get(0);
        assertThat(r.team()).isEqualTo("AWY");
        assertThat(r.side()).isEqualTo("away");
        assertThat(r.line()).isEqualTo(1.5);
        assertThat(r.coverProb()).isEqualTo(0.58);          // 1 - favCover(0.42)
        assertThat(r.edge()).isEqualTo(0.157);              // 0.58 - 0.44/1.04
    }

    @Test
    void runLine_edgePath_awayFavoriteReadsThePlus15Column() {
        // AWY is the book favorite: fav cover = 1 - pHomeCoverPlus15 = 0.65 vs fair 0.5769
        // → favorite side keeps the edge, labeled AWY -1.5.
        RunLineDto r = board(row(8.5, 0.60, 0.44, "away", 0.35)).runLine().get(0);
        assertThat(r.team()).isEqualTo("AWY");
        assertThat(r.side()).isEqualTo("away");
        assertThat(r.line()).isEqualTo(-1.5);
        assertThat(r.coverProb()).isEqualTo(0.65);
    }

    @Test
    void runLine_noOdds_fallsBackToSimFavoriteWithoutAnEdge() {
        // pHomeCoverPlus15 present: away -1.5 cover = 1 - 0.70 = 0.30 < home's 0.42 →
        // home is the sim favorite. No odds → no edge/bookLine on the DTO.
        RunLineDto r = board(row(8.5, null, null, null, 0.70)).runLine().get(0);
        assertThat(r.team()).isEqualTo("HOM");
        assertThat(r.line()).isEqualTo(-1.5);
        assertThat(r.edge()).isNull();
        assertThat(r.bookLine()).isNull();
    }

    @Test
    void runLine_preV69Row_usesTheLegacyHeuristic() {
        // pHomeCoverPlus15 null and no odds: legacy compares pHomeCover15 (0.42) vs
        // pAwayCover15 (0.30) → home favorite.
        RunLineDto r = board(row(8.5, null, null, null, null)).runLine().get(0);
        assertThat(r.team()).isEqualTo("HOM");
        assertThat(r.coverProb()).isEqualTo(0.42);
    }
}
