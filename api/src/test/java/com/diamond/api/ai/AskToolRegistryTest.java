package com.diamond.api.ai;

import com.diamond.api.dto.AccuracyResponse;
import com.diamond.api.dto.PlayerDetailDto;
import com.diamond.api.dto.RecentStatDto;
import com.diamond.api.repository.PlayerStatRepository;
import com.diamond.api.service.AccuracyService;
import com.diamond.api.service.GameService;
import com.diamond.api.service.MostLikelyService;
import com.diamond.api.service.OddsService;
import com.diamond.api.service.ProjectionService;
import com.diamond.api.service.PropBoardService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Verifies the AI tool surface: tool definitions are exposed, names dispatch to the right
 * service, results come back as JSON, and bad/unknown calls fail soft (JSON error) so the
 * model can recover. Stubs the services (no DB / Spring context), house style.
 */
class AskToolRegistryTest {

    private static final PlayerDetailDto JUDGE =
        new PlayerDetailDto(592450, "Aaron Judge", 147, "NYY", "RF", "R", "R");

    private static AskToolRegistry registry() {
        PlayerStatRepository players = new PlayerStatRepository(null) {
            @Override
            public List<PlayerDetailDto> searchByName(String query, int limit) {
                return List.of(JUDGE);
            }

            @Override
            public Optional<PlayerDetailDto> findById(int playerId) {
                return Optional.of(JUDGE);
            }

            @Override
            public List<RecentStatDto> findRecent(int playerId, int limit) {
                return List.of(new RecentStatDto("2026-06-15", "BOS", true, 4, 2, 1, 1, 0.421));
            }
        };
        AccuracyService accuracy = new AccuracyService(null) {
            @Override
            public AccuracyResponse accuracy(int days) {
                return new AccuracyResponse(days, "v2026", List.of());
            }
        };
        return new AskToolRegistry(
            new GameService(null), new ProjectionService(null, null), new OddsService(null, null),
            new PropBoardService(null, null), new MostLikelyService(null), accuracy,
            players, new ObjectMapper());
    }

    private static Map<String, Object> input(Map<String, Object> fields) {
        return fields;
    }

    @Test
    void exposesTheFullToolMenu() {
        List<String> names = registry().declarations().stream()
            .map(d -> d.name().orElseThrow())
            .toList();
        assertThat(names).containsExactlyInAnyOrder(
            "get_today_games", "get_game_projections", "get_best_plays", "get_prop_board",
            "get_most_likely", "search_player", "get_player", "get_model_accuracy");
    }

    @Test
    void searchPlayerReturnsMatchesAsJson() {
        String json = registry().execute("search_player", input(Map.of("name", "judge")));
        assertThat(json).contains("Aaron Judge").contains("592450");
    }

    @Test
    void getPlayerBundlesDetailAndRecentForm() {
        String json = registry().execute("get_player", input(Map.of("playerId", "592450")));
        assertThat(json).contains("\"player\"").contains("\"recent\"").contains("Aaron Judge");
    }

    @Test
    void modelAccuracyDefaultsToThirtyDays() {
        String json = registry().execute("get_model_accuracy", input(Map.of()));
        assertThat(json).contains("\"days\":30");
    }

    @Test
    void unknownToolFailsSoftAsJsonError() {
        assertThat(registry().execute("get_world_peace", input(Map.of()))).contains("\"error\"");
    }

    @Test
    void missingRequiredParamFailsSoftAsJsonError() {
        String json = registry().execute("get_game_projections", input(Map.of()));
        assertThat(json).contains("\"error\"").contains("gameId");
    }

    @Test
    void getPlayerMapsToThePlayerPageWithName() {
        AskToolRegistry r = registry();
        String result = r.execute("get_player", input(Map.of("playerId", "592450")));
        LinkRef link = r.linkFor("get_player", input(Map.of("playerId", "592450")), result).orElseThrow();
        assertThat(link.href()).isEqualTo("/mlb/players/592450");
        assertThat(link.label()).isEqualTo("Aaron Judge");
    }

    @Test
    void boardToolsMapToTheirRoutes() {
        AskToolRegistry r = registry();
        assertThat(r.linkFor("get_best_plays", input(Map.of()), "[]").orElseThrow().href())
            .isEqualTo("/mlb/odds");
        assertThat(r.linkFor("search_player", input(Map.of("name", "x")), "[]")).isEmpty();
    }

    @Test
    void labelsAreHumanFriendlyWithAFallback() {
        AskToolRegistry r = registry();
        assertThat(r.label("get_today_games")).isEqualTo("Checking tonight's MLB slate…");
        assertThat(r.label("nonexistent")).isEqualTo("Looking that up…");
    }
}
