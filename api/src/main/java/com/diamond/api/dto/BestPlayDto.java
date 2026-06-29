package com.diamond.api.dto;

/**
 * One model-edged selection for the "Today's Best Lines" board (GET /api/odds/best).
 * {@code side} is the raw side token (over/under for props & totals; home/away for
 * moneyline/run line) so the UI can render Over/Under and team columns distinctly.
 * {@code fairProb} is the no-vig market probability for this side (null if not de-vigged);
 * the board's edge metric is modelProb − fairProb.
 */
public record BestPlayDto(
    long gameId,
    String matchup,
    String market,
    String side,
    String selection,
    Double line,
    String bestBook,
    int priceAmerican,
    double priceDecimal,
    double modelProb,
    double impliedProb,
    Double fairProb,
    double evPct,
    Integer playerId,
    String playerName,
    // Analyst promotion-gate verdict (V64). Null when not vetted (AI off / not yet debated) —
    // the board treats null as "show mechanically". 'pass' demotes from Today's Board to here.
    String debateVerdict,
    Double debateConfidence,
    String debateRationale
) {}
