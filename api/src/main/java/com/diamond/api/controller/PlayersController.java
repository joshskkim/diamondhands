package com.diamond.api.controller;

import com.diamond.api.dto.PlayerDetailDto;
import com.diamond.api.dto.RecentStatDto;
import com.diamond.api.dto.SprayResponse;
import com.diamond.api.repository.PlayerStatRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
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

    /** Spray-direction bins for the hot-zone visual; empty bins = below the BIP gate. */
    @GetMapping("/{playerId}/spray")
    public ResponseEntity<SprayResponse> spray(
        @PathVariable int playerId,
        @RequestParam(required = false) Integer season
    ) {
        return playerStatRepository.findById(playerId)
            .map(p -> {
                int target = season != null ? season : LocalDate.now().getYear();
                List<SprayResponse.SprayBinDto> bins =
                    playerStatRepository.findSprayBins(playerId, target);
                int totalBip = bins.stream().mapToInt(SprayResponse.SprayBinDto::bip).sum();
                return ResponseEntity.ok(
                    new SprayResponse(playerId, target, p.bats(), totalBip, bins));
            })
            .orElse(ResponseEntity.notFound().build());
    }
}
