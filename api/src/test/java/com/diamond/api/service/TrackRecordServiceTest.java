package com.diamond.api.service;

import com.diamond.api.dto.RecordSummaryDto;
import com.diamond.api.dto.TrackRecordResponse;
import com.diamond.api.repository.TrackRecordRepository;
import com.diamond.api.repository.TrackRecordRepository.SettledPick;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** Locks the units / ROI / win% / Brier math and the push/void classification. */
class TrackRecordServiceTest {

    private static final LocalDate D1 = LocalDate.of(2026, 6, 18);
    private static final LocalDate D2 = LocalDate.of(2026, 6, 19);

    private static SettledPick pick(LocalDate day, String market, boolean strong,
                                    Boolean won, double modelProb, int price, Double resultValue) {
        return pick(day, market, strong, won, modelProb, price, resultValue, "v2.12.0");
    }

    private static SettledPick pick(LocalDate day, String market, boolean strong, Boolean won,
                                    double modelProb, int price, Double resultValue, String version) {
        return new SettledPick(day, market, strong, won, modelProb, price, resultValue, version, false);
    }

    private static SettledPick lottoPick(LocalDate day, String market, Boolean won,
                                         double modelProb, int price, Double resultValue) {
        return new SettledPick(day, market, false, won, modelProb, price, resultValue, "v2.12.0", true);
    }

    private TrackRecordResponse serve(List<SettledPick> picks) {
        TrackRecordRepository repo = mock(TrackRecordRepository.class);
        when(repo.settledSince(any(LocalDate.class))).thenReturn(picks);
        return new TrackRecordService(repo).trackRecord(60);
    }

    @Test
    void aggregatesRecordUnitsRoiAndBrier() {
        TrackRecordResponse r = serve(List.of(
            pick(D1, "total", true, true, 0.60, 150, 9.0, "v2.12.0"),       // WIN  +1.50u
            pick(D1, "hr", false, false, 0.20, 400, 0.0, "v2.11.0"),        // LOSS -1.00u
            pick(D2, "total", false, null, 0.55, -110, 8.0, "v2.12.0"),     // PUSH  0.00u
            pick(D2, "moneyline", false, null, 0.50, -120, null, "v9.9.9")  // VOID — excluded entirely
        ));

        RecordSummaryDto o = r.overall();
        assertThat(o.wins()).isEqualTo(1);
        assertThat(o.losses()).isEqualTo(1);
        assertThat(o.pushes()).isEqualTo(1);
        assertThat(o.n()).isEqualTo(3);                 // void not counted
        assertThat(o.units()).isEqualTo(0.5);           // 1.5 - 1 + 0
        assertThat(o.winPct()).isEqualTo(0.5);          // 1 of 2 decided
        assertThat(o.roiPct()).isEqualTo(16.67);        // 0.5 / 3 * 100
        assertThat(r.pickBrier()).isEqualTo(0.1);       // (0.16 + 0.04) / 2
        assertThat(r.asOf()).isEqualTo("2026-06-19");
        // Distinct versions across counted picks, sorted; the void pick's v9.9.9 is excluded.
        assertThat(r.modelVersions()).containsExactly("v2.11.0", "v2.12.0");

        // moneyline was void-only → dropped from the market breakdown.
        assertThat(r.byMarket()).extracting(RecordSummaryDto::label)
            .containsExactly("total", "hr");
        assertThat(r.byTier()).extracting(RecordSummaryDto::label)
            .containsExactly("Strong", "Standard");

        // Equity: one point per day, cumulative.
        assertThat(r.equity()).hasSize(2);
        assertThat(r.equity().get(1).cumUnits()).isEqualTo(0.5);
        assertThat(r.equity().get(1).cumWins()).isEqualTo(1);
        assertThat(r.equity().get(1).cumLosses()).isEqualTo(1);
    }

    @Test
    void emptyWindowYieldsNullBrierAndAsOf() {
        TrackRecordResponse r = serve(List.of());
        assertThat(r.overall().n()).isZero();
        assertThat(r.pickBrier()).isNull();
        assertThat(r.asOf()).isNull();
        assertThat(r.byMarket()).isEmpty();
        assertThat(r.modelVersions()).isEmpty();
    }

    @Test
    void lottoPicksFormTheirOwnTier() {
        TrackRecordResponse r = serve(List.of(
            pick(D1, "total", true, true, 0.60, -110, 9.0),   // Strong WIN
            pick(D1, "hr", false, false, 0.20, 400, 0.0),     // Standard LOSS
            lottoPick(D2, "hr", true, 0.10, 800, 2.0)         // Lotto WIN  +8.00u
        ));

        assertThat(r.byTier()).extracting(RecordSummaryDto::label)
            .containsExactly("Strong", "Standard", "Lotto");
        RecordSummaryDto lotto = r.byTier().stream()
            .filter(t -> t.label().equals("Lotto")).findFirst().orElseThrow();
        assertThat(lotto.wins()).isEqualTo(1);
        assertThat(lotto.units()).isEqualTo(8.0);  // +800 → decimal 9.0 → +8.00u
    }

    @Test
    void decimalOddsConversion() {
        assertThat(TrackRecordService.decimalOdds(150)).isEqualTo(2.5);
        assertThat(TrackRecordService.decimalOdds(-200)).isEqualTo(1.5);
    }
}
