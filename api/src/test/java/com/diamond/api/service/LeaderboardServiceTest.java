package com.diamond.api.service;

import com.diamond.api.dto.PitchTypeLeaderboardDto;
import com.diamond.api.repository.PitchRepository;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Verifies the pitch-type leaderboard applies empirical-Bayes regression and returns
 * rows sorted by xwOBA edge descending. Uses a stub repository (no DB / Spring context).
 */
class LeaderboardServiceTest {

    private static PitchRepository repoReturning(List<PitchRepository.LeaderboardRow> rows) {
        return new PitchRepository(null) {
            @Override
            public List<LeaderboardRow> leaderboardCandidates(String pitch, LocalDate date) {
                return rows;
            }
        };
    }

    @Test
    void leaderboardSortsByEdgeDescAndRegresses() {
        // A: .400 raw over 1000 pitches vs league .300 → regressed ≈ .391, edge ≈ +.091
        // C: .360 raw over  200 pitches vs league .300 → regressed ≈ .340, edge ≈ +.040
        // B: .250 raw over 1000 pitches vs league .300 → regressed ≈ .255, edge ≈ -.046
        var rows = List.of(
            new PitchRepository.LeaderboardRow(1, "A", "AAA", 10, "P1", "R", 0.50, 0.400, 1000, 0.300),
            new PitchRepository.LeaderboardRow(2, "B", "BBB", 11, "P2", "L", 0.40, 0.250, 1000, 0.300),
            new PitchRepository.LeaderboardRow(3, "C", "CCC", 12, "P3", "R", 0.30, 0.360, 200, 0.300));

        var out = new LeaderboardService(repoReturning(rows)).pitchTypeLeaderboard("FF", LocalDate.now(), 20);

        assertThat(out).hasSize(3);
        assertThat(out.stream().map(r -> r.player().id())).containsExactly(1, 3, 2);
        // Strictly descending edges.
        assertThat(out.get(0).edge()).isGreaterThan(out.get(1).edge());
        assertThat(out.get(1).edge()).isGreaterThan(out.get(2).edge());
        // Regression pulls the 200-pitch sample further toward league than the raw value.
        assertThat(out.get(1).batterXwoba()).isLessThan(0.360).isGreaterThan(0.300);
    }

    @Test
    void respectsLimit() {
        var rows = List.of(
            new PitchRepository.LeaderboardRow(1, "A", "AAA", 10, "P1", "R", 0.50, 0.400, 1000, 0.300),
            new PitchRepository.LeaderboardRow(2, "B", "BBB", 11, "P2", "L", 0.40, 0.380, 1000, 0.300));
        var out = new LeaderboardService(repoReturning(rows)).pitchTypeLeaderboard("FF", LocalDate.now(), 1);
        assertThat(out).hasSize(1);
        assertThat(out.get(0).player().id()).isEqualTo(1);  // highest edge kept
    }

    @Test
    void pitchTypesHasSevenBuckets() {
        var types = new LeaderboardService(repoReturning(List.of())).pitchTypes();
        assertThat(types).hasSize(7);
        assertThat(types.stream().map(t -> t.code()))
            .containsExactly("FF", "SI", "FC", "SL", "CU", "CH", "FS");
    }
}
