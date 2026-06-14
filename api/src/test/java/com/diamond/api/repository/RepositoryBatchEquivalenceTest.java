package com.diamond.api.repository;

import com.diamond.api.dto.BatterProjectionDto;
import com.diamond.api.repository.PitchRepository.BatterPitchRow;
import com.diamond.api.repository.ProjectionRepository.BatterRow;
import com.diamond.api.repository.PropBoardRepository.SlateRow;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Proves the batched repository queries (added to collapse the per-batter / per-candidate
 * N+1s) return byte-identical results to N single-key calls. Runs against the local dev DB;
 * skips cleanly via {@code assumeTrue} when the slate for the test date has no data.
 */
@SpringBootTest
class RepositoryBatchEquivalenceTest {

    @Autowired private PitchRepository pitchRepo;
    @Autowired private PropBoardRepository propRepo;
    @Autowired private ProjectionRepository projRepo;
    @Autowired private OddsRepository oddsRepo;
    @Autowired private JdbcTemplate jdbc;

    private final LocalDate date = LocalDate.now();

    @Test
    void clearRatesBatchMatchesPerPlayer() {
        List<SlateRow> slate = propRepo.findSlateRows(date);
        assumeTrue(!slate.isEmpty(), "no slate data for " + date);

        List<Integer> ids = slate.stream().map(SlateRow::playerId).distinct().limit(25).toList();
        Map<Integer, PropBoardRepository.ClearRates> batch = propRepo.findClearRatesBatch(ids, date);

        for (Integer id : ids) {
            assertThat(batch.get(id))
                .as("clear rates for player %s", id)
                .isEqualTo(propRepo.findClearRates(id, date));
        }
    }

    @Test
    void arsenalAndBatterPitchBatchMatchPerBatter() {
        Long gameId = jdbc.query(
            "SELECT id FROM games WHERE game_date = ? ORDER BY id LIMIT 1",
            rs -> rs.next() ? rs.getLong(1) : null, date);
        assumeTrue(gameId != null, "no game on " + date);

        List<BatterRow> rows = projRepo.findByGameId(gameId);
        assumeTrue(!rows.isEmpty(), "no projections for game " + gameId);
        LocalDate asOf = rows.get(0).gameDate();
        assumeTrue(asOf != null, "null game date");

        Map<Integer, String> pitcherHandById = new HashMap<>();
        Set<Integer> batterIds = new HashSet<>();
        Set<String> batterHands = new HashSet<>();
        Set<String> pitcherHands = new HashSet<>();
        for (BatterRow row : rows) {
            BatterProjectionDto p = row.projection();
            String pitcherHand = p.opposingPitcher().throws_();
            if (pitcherHand == null) continue;
            pitcherHandById.put(p.opposingPitcher().id(), pitcherHand);
            batterIds.add(p.player().id());
            pitcherHands.add(pitcherHand);
            batterHands.add(effHand(p.player().bats(), pitcherHand));
        }
        assumeTrue(!pitcherHandById.isEmpty(), "no opposing-pitcher hands available");

        Map<String, List<com.diamond.api.dto.PitchArsenalDto>> arsBatch =
            pitchRepo.arsenalBatch(pitcherHandById, batterHands, asOf);
        Map<String, Map<String, BatterPitchRow>> bpBatch =
            pitchRepo.batterPitchStatsBatch(batterIds, pitcherHands, asOf);

        for (BatterRow row : rows) {
            BatterProjectionDto p = row.projection();
            String pitcherHand = p.opposingPitcher().throws_();
            if (pitcherHand == null) continue;
            int pitcherId = p.opposingPitcher().id();
            int batterId = p.player().id();
            String batterHand = effHand(p.player().bats(), pitcherHand);

            assertThat(arsBatch.getOrDefault(pitcherId + "|" + batterHand, List.of()))
                .as("arsenal for pitcher %s vs %s", pitcherId, batterHand)
                .isEqualTo(pitchRepo.arsenal(pitcherId, pitcherHand, batterHand, asOf));

            Map<String, BatterPitchRow> single = pitchRepo.batterPitchStats(batterId, pitcherHand, asOf)
                .stream()
                .collect(Collectors.toMap(BatterPitchRow::pitchType, Function.identity(), (a, b) -> a));
            assertThat(bpBatch.getOrDefault(batterId + "|" + pitcherHand, Map.of()))
                .as("batter pitch stats for %s vs %s", batterId, pitcherHand)
                .isEqualTo(single);
        }
    }

    @Test
    void oddsByDateBatchMatchesPerGame() {
        java.sql.Date d = jdbc.query(
            "SELECT max(g.game_date) FROM game_odds go JOIN games g ON g.id = go.game_id",
            rs -> rs.next() ? rs.getDate(1) : null);
        assumeTrue(d != null, "no stored game odds");
        LocalDate oddsDate = d.toLocalDate();

        var gameOddsByGame = oddsRepo.findGameOddsByDate(oddsDate);
        var propsByGame = oddsRepo.findPropOddsByDate(oddsDate);
        var projByGame = oddsRepo.findRunProjByDate(oddsDate);
        var metaByGame = oddsRepo.findGameMetaByDate(oddsDate);

        List<Long> gameIds = oddsRepo.findGameIdsWithOdds(oddsDate);
        assumeTrue(!gameIds.isEmpty(), "no games with odds on " + oddsDate);

        for (Long gid : gameIds) {
            assertThat(gameOddsByGame.getOrDefault(gid, List.of()))
                .as("game odds for %s", gid).isEqualTo(oddsRepo.findGameOdds(gid));
            assertThat(propsByGame.getOrDefault(gid, List.of()))
                .as("prop odds for %s", gid).isEqualTo(oddsRepo.findPropOdds(gid));
            assertThat(projByGame.get(gid))
                .as("run proj for %s", gid).isEqualTo(oddsRepo.findRunProj(gid));
            assertThat(metaByGame.get(gid))
                .as("meta for %s", gid).isEqualTo(oddsRepo.findGameMeta(gid));
        }
    }

    /** Mirrors ProjectionService.effectiveHand (switch hitters bat opposite the pitcher). */
    private static String effHand(String bats, String pitcherThrows) {
        if ("S".equals(bats)) return "R".equals(pitcherThrows) ? "L" : "R";
        return ("L".equals(bats) || "R".equals(bats)) ? bats : "R";
    }
}
