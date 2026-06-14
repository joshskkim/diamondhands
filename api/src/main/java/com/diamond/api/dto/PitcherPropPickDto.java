package com.diamond.api.dto;

import java.util.List;

/**
 * The model's headline starting pitcher for one pitcher-prop market (strikeouts or
 * outs recorded), ranked by the workload model's EXPECTED VOLUME — not by P(clears
 * his line), since pitcher lines vary by arm (a soft-tosser's 3.5 K line clears more
 * easily than an ace's 6.5) and ranking on that would surface the wrong pitchers.
 *
 * {@code expectedValue} is the headline projection (expected Ks or outs). {@code
 * distribution} is the over-probability at each book-standard threshold from the
 * workload model. Odds fields are the best cached over-price and are null when odds
 * haven't been pulled — the card stands on the projection alone.
 */
public record PitcherPropPickDto(
    String market,           // "pitcher_k" | "pitcher_outs"
    long gameId,
    String matchup,
    int pitcherId,
    String pitcher,
    String team,
    String opponent,         // the lineup he faces
    double expectedValue,
    Double expectedIp,
    List<Threshold> distribution,
    Double bookLine,
    String bestBook,
    Integer priceAmerican,
    Double evPct,
    List<RunnerUp> runnersUp
) {
    /** One over-threshold from the workload distribution: P(over {@code line}). */
    public record Threshold(double line, double prob) {}

    /** An honorable mention: same expected-volume ranking, no distribution. */
    public record RunnerUp(int pitcherId, String pitcher, String team, double expectedValue) {}
}
