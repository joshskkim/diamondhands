package com.diamond.api.dto;

import java.util.List;

/**
 * The headline starting pitcher for one pitcher-prop market (strikeouts, outs,
 * hits allowed, earned runs), ranked by MODEL-VS-LINE EDGE: |model P(over) −
 * de-vigged book P(over)| at the pitcher's consensus line, with the recommended
 * side wherever the edge points ({@code rankedBy} = "edge"). A market with no
 * beatable two-way line produces no card at all, so a card is always an edge pick.
 *
 * {@code expectedValue} is the headline projection (expected Ks / outs / hits /
 * ER). {@code distribution} is the over-probability at each modeled threshold.
 * Odds fields are the best cached price for the recommended side.
 */
public record PitcherPropPickDto(
    String market,           // "pitcher_k" | "pitcher_outs" | "pitcher_hits_allowed" | "pitcher_earned_runs"
    long gameId,
    String matchup,
    int pitcherId,
    String pitcher,
    String team,
    String opponent,         // the lineup he faces
    double expectedValue,
    Double expectedIp,
    List<Threshold> distribution,
    // The single recommended pick: the side of the positive edge at the book's consensus
    // line. bestProb is that side's model probability.
    Double bestLine,
    String bestSide,         // "over" | "under"
    Double bestProb,
    // Best cached price + EV for the RECOMMENDED side at bestLine (null when no odds).
    Double bookLine,
    String bestBook,
    Integer priceAmerican,
    Double evPct,
    // |model − no-vig| probability gap and the de-vigged book probability for the
    // recommended side; how this card was ranked (always "edge").
    Double edge,
    Double fairProb,
    String rankedBy,         // "edge"
    // Reasoning drivers (null when skill rows are absent): the pitcher's own BF-weighted
    // profile, the opposing lineup's PA-weighted K rate / xwOBA, and the pitcher's top
    // pitches by usage (empty list when no arsenal snapshot exists).
    Double pitcherKRate,
    Double pitcherBbRate,
    Double pitcherXwobaAgainst,
    Double pitcherHrPerPa,
    Double opponentKRate,
    Double opponentXwoba,
    List<ArsenalPitch> arsenal,
    List<RunnerUp> runnersUp
) {
    /** One over-threshold from the workload distribution: P(over {@code line}). */
    public record Threshold(double line, double prob) {}

    /** A runner-up starter for this market, in the same edge order as the headline pick:
     *  its recommended side and model-vs-line edge, plus the headline projection for context. */
    public record RunnerUp(int pitcherId, String pitcher, String team, double expectedValue,
                           String bestSide, Double edge) {}

    /** One pitch in the starter's mix: usage / whiff / velocity (any may be null). */
    public record ArsenalPitch(String pitchType, Double usageRate, Double whiffRate, Double avgVelocity) {}
}
