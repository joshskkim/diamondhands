package com.diamond.api.controller;

import com.diamond.api.dto.PlayerDetailDto;
import com.diamond.api.repository.PlayerStatRepository;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Name-search endpoint: delegates to the repository and clamps the limit to 1..8 (the same
 * cap the in-app search_player tool uses), so a caller can't request an unbounded result set.
 */
class PlayersControllerTest {

    private record Captured(String query, int limit) {}

    private static PlayersController controllerCapturing(AtomicReference<Captured> sink) {
        PlayerStatRepository repo = new PlayerStatRepository(new JdbcTemplate()) {
            @Override
            public List<PlayerDetailDto> searchByName(String query, int limit) {
                sink.set(new Captured(query, limit));
                return List.of(new PlayerDetailDto(1, "Aaron Judge", 147, "NYY", "RF", "R", "R"));
            }
        };
        return new PlayersController(repo);
    }

    @Test
    void searchDelegatesWithDefaultLimit() {
        AtomicReference<Captured> captured = new AtomicReference<>();
        List<PlayerDetailDto> result = controllerCapturing(captured).search("judge", 8);

        assertThat(captured.get().query()).isEqualTo("judge");
        assertThat(captured.get().limit()).isEqualTo(8);
        assertThat(result).singleElement()
            .extracting(PlayerDetailDto::fullName).isEqualTo("Aaron Judge");
    }

    @Test
    void searchClampsLimitToEight() {
        AtomicReference<Captured> captured = new AtomicReference<>();
        controllerCapturing(captured).search("a", 1000);
        assertThat(captured.get().limit()).isEqualTo(8);
    }

    @Test
    void searchClampsLimitToAtLeastOne() {
        AtomicReference<Captured> captured = new AtomicReference<>();
        controllerCapturing(captured).search("a", 0);
        assertThat(captured.get().limit()).isEqualTo(1);
    }
}
