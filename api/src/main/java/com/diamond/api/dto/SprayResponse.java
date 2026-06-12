package com.diamond.api.dto;

import java.util.List;

/**
 * GET /api/players/{id}/spray — a batter's spray-direction bins for one season.
 * Bins are FIELD-absolute: nine 10° sectors from the LF foul line (bin 0) to the
 * RF line (bin 8); clients mirror by {@code bats} when they want pull-relative.
 * Empty {@code bins} = no season at/above the 50-BIP aggregation gate.
 */
public record SprayResponse(
    int playerId,
    int season,
    String bats,
    int totalBip,
    List<SprayBinDto> bins
) {
    /** One 10° sector: balls in play, homers, and average Statcast hit distance. */
    public record SprayBinDto(int bin, int bip, int hr, Double avgDistanceFt) {}
}
