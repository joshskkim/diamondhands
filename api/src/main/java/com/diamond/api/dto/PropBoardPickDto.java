package com.diamond.api.dto;

/**
 * The model's single most-likely batter for one prop market (hit / hr / k, all 0.5
 * lines), with every factor the client needs to explain the number: opposing pitcher
 * and matchup quality, park/pitcher/weather multipliers, lineup slot, recent and
 * season clear-rates. Price fields are the best cached sportsbook over-price and are
 * null whenever odds haven't been pulled — the pick stands on the model alone.
 */
public record PropBoardPickDto(
    String market,
    double line,
    long gameId,
    String matchup,
    int playerId,
    String player,
    String team,
    Integer lineupPosition,
    Boolean lineupConfirmed,
    Double expectedPa,
    double prob,
    Integer opposingPitcherId,
    String opposingPitcher,
    String pitcherDataQuality,
    Double matchupXwoba,
    String matchupQuality,
    Double adjPark,
    Double adjPitcher,
    Double adjWeather,
    String stadium,
    Double rateL10,
    Double rateSeason,
    Integer nSeason,
    String bestBook,
    Integer priceAmerican,
    Double priceDecimal,
    Double evPct
) {}
