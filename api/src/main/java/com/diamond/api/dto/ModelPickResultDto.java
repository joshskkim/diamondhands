package com.diamond.api.dto;

/**
 * A persisted Model's Pick for a slate, with its graded outcome. Recorded by the
 * ingester's {@code record-picks} and graded by {@code score-picks}: {@code won} is
 * true/false once actuals land, null while still pending (or on a push/void).
 * {@code resultValue} is the actual total / hits / HR / run margin.
 *
 * <p>A pick stays on record once shown. {@code active} is true for the current top set
 * and false for picks a better late pick later displaced (still graded + counted, shown
 * as "earlier" extras). {@code firstShownAt} is when it first made the board (its locked
 * line is the price at that moment); {@code bumpedAt} is set when it was displaced.
 */
public record ModelPickResultDto(
    String slateDate,
    Integer rank,            // board order among active picks; null for bumped/frozen rows
    long gameId,
    String market,           // total | moneyline | run_line | hit | hr
    String side,
    Double line,
    Integer playerId,
    String playerName,
    String matchup,
    Double modelProb,
    Double fairProb,
    Double edge,
    Double evPct,
    Integer priceAmerican,
    String book,
    boolean strong,
    Double resultValue,
    Boolean won,
    boolean scored,
    boolean active,
    String firstShownAt,
    String bumpedAt,
    // Analyst promotion-gate verdict (V64) — what endorsed this pick onto the board.
    String debateVerdict,
    Double debateConfidence,
    String debateRationale
) {}
