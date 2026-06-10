package com.diamond.api.dto;

/**
 * Outlier-style hit-rate "traffic light" for one batter prop market: how often the
 * player has cleared the prop's line over their last 5/10/20 games and the current
 * season. Keyed by playerId + market so the client can join it to a Best Lines row.
 * Rates are 0..1 (null when the window has no games); n20 / nSeason are sample sizes.
 */
public record HitRateDto(
    int playerId,
    String market,
    double line,
    Double l5,
    Double l10,
    Double l20,
    int n20,
    Double season,
    int nSeason
) {}
