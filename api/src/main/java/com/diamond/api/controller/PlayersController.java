package com.diamond.api.controller;

import com.diamond.api.dto.PlayerDetailDto;
import com.diamond.api.dto.RecentStatDto;
import com.diamond.api.repository.PlayerStatRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/players")
public class PlayersController {

    private final PlayerStatRepository playerStatRepository;

    public PlayersController(PlayerStatRepository playerStatRepository) {
        this.playerStatRepository = playerStatRepository;
    }

    @GetMapping("/{playerId}")
    public ResponseEntity<PlayerDetailDto> getPlayer(@PathVariable int playerId) {
        return playerStatRepository.findById(playerId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping("/{playerId}/recent")
    public List<RecentStatDto> recent(
        @PathVariable int playerId,
        @RequestParam(defaultValue = "20") int limit
    ) {
        int safeLimit = Math.min(Math.max(limit, 1), 100);
        return playerStatRepository.findRecent(playerId, safeLimit);
    }
}
