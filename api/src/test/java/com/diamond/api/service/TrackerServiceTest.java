package com.diamond.api.service;

import com.diamond.api.dto.TrackerResponse;
import com.diamond.api.dto.TrackerResponse.TrackerEntry;
import com.diamond.api.repository.TrackerRepository;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The Tracker summary math (record / units / ROI / CLV) over a user's tailed picks + bets.
 * Pending rows don't count toward the record; CLV averages over every row that has it.
 */
class TrackerServiceTest {

    private static TrackerEntry entry(String source, Integer price, Double stake, Boolean won,
                                      Double resultValue, Double clv, boolean scored) {
        return new TrackerEntry(1, source, "2026-06-29", 100L, "total", "over", 8.5, null, null,
            price, "fd", stake, null, 0.58, 0.51, 0.07, won, resultValue, clv, scored, "tracked");
    }

    private static TrackerService serviceWith(List<TrackerEntry> recs, List<TrackerEntry> bets) {
        TrackerRepository repo = new TrackerRepository(null) {
            @Override public List<TrackerEntry> findRecommendations(long userId) { return recs; }
            @Override public List<TrackerEntry> findBets(long userId) { return bets; }
        };
        return new TrackerService(repo, null, null, null);
    }

    @Test
    void summarizesRecordUnitsRoiAndClv() {
        // won +100 (dec 2.0) at 2u => +2u; lost -110 at 1u => -1u; one pending (ignored).
        List<TrackerEntry> recs = List.of(
            entry("agent", 100, 2.0, true, 1.0, 0.03, true),
            entry("agent", -110, 1.0, false, 0.0, -0.01, true),
            entry("agent", -110, 1.0, null, null, null, false));   // pending
        TrackerResponse r = serviceWith(recs, List.of()).tracked(1);

        assertThat(r.entries()).hasSize(3);
        assertThat(r.summary().picks()).isEqualTo(2);      // pending excluded
        assertThat(r.summary().wins()).isEqualTo(1);
        assertThat(r.summary().losses()).isEqualTo(1);
        assertThat(r.summary().units()).isEqualTo(1.0);    // +2 - 1
        assertThat(r.summary().roiPct()).isEqualTo(50.0);  // 1u over 2 graded
        assertThat(r.summary().clvN()).isEqualTo(2);
        assertThat(r.summary().avgClv()).isEqualTo(0.01);
        assertThat(r.summary().clvRate()).isEqualTo(0.5);
    }

    @Test
    void mergesBetsAndPicksNewestFirst() {
        TrackerEntry older = new TrackerEntry(2, "personal", "2026-06-27", 1L, "hr", "over", 0.5,
            10, "A B", -120, "dk", 1.0, null, null, null, null, null, null, null, false, "open");
        TrackerResponse r = serviceWith(
            List.of(entry("agent", 100, 1.0, true, 1.0, null, true)),
            List.of(older)).tracked(1);
        assertThat(r.entries().get(0).slateDate()).isEqualTo("2026-06-29"); // newest first
        assertThat(r.entries().get(1).source()).isEqualTo("personal");
    }
}
