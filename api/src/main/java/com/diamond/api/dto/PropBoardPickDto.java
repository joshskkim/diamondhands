package com.diamond.api.dto;

import java.util.List;

/**
 * The model's single most-likely batter for one prop market (hit / hr / k, all 0.5
 * lines), with every factor the client needs to explain the number: opposing pitcher
 * and matchup quality, park/pitcher/weather multipliers, lineup slot, recent and
 * season clear-rates. Price fields are the best cached sportsbook over-price and are
 * null whenever odds haven't been pulled — the pick stands on the model alone.
 *
 * {@code prob} is the DISPLAYED probability: the model's number shrunk toward the
 * player's own season clear-rate by sample size (see PropBoardService.blend).
 * {@code probModel} is the raw model output, kept for transparency. {@code runnersUp}
 * are the next two batters by the same blended ranking — honorable mentions, no
 * explanations.
 *
 * Park-fit fields ({@code pullPct}/{@code fbPct}/{@code avgLaunchSpeed} from the
 * batter's current-season batted-ball profile; {@code pullFenceFt}/{@code pullWallFt}
 * = the fence his handedness pulls toward) are raw facts for the HR card's reasoning —
 * the personalization multiplier itself stays in the Python model. All nullable:
 * missing profile, switch hitter (no single pull side), or missing fence data.
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
    double probModel,
    Integer opposingPitcherId,
    String opposingPitcher,
    String pitcherDataQuality,
    Double matchupXwoba,
    String matchupQuality,
    Double adjPark,
    Double adjPitcher,
    Double adjWeather,
    String stadium,
    String bats,
    Double pullPct,
    Double fbPct,
    Double avgLaunchSpeed,
    Double pullFenceFt,
    Double pullWallFt,
    Double rateL10,
    Double rateSeason,
    Integer nSeason,
    String bestBook,
    Integer priceAmerican,
    Double priceDecimal,
    Double evPct,
    List<RunnerUp> runnersUp
) {
    /** An honorable mention: same blended ranking, no explanation payload. */
    public record RunnerUp(int playerId, String player, String team, double prob) {}
}
