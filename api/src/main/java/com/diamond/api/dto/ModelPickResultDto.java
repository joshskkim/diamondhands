package com.diamond.api.dto;

/**
 * A persisted Model's Pick for a slate, with its graded outcome. Recorded nightly by
 * the ingester's {@code record-picks} and graded by {@code score-picks}: {@code won}
 * is true/false once actuals land, null while still pending (or on a push/void).
 * {@code resultValue} is the actual total / hits / HR / run margin.
 */
public record ModelPickResultDto(
    String slateDate,
    int rank,
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
    boolean lotto,           // true = the off-board "Lotto" moonshot (rank N+1)
    Double resultValue,
    Boolean won,
    boolean scored
) {}
