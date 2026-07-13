package com.diamond.api.dto;

/**
 * A persisted Model's Pick for a slate, with its graded outcome. Recorded by the
 * ingester's {@code record-picks} and graded by {@code score-picks}: {@code won} is
 * true/false once actuals land, null while still pending (or on a push/void).
 * {@code resultValue} is the actual total / hits / HR / run margin.
 *
 * <p>A pick stays on record once shown, locked at its first-shown line. {@code active}
 * is true for the current board and false for rows taken off it — {@code bumpReason}
 * says why: 'lineup' (the game's lineup changed after lock and the pick no longer
 * cleared the bar) or 'displaced' (legacy pre-budget churn: a better late play replaced
 * it). Bumped rows are still graded + counted, shown as "earlier" extras.
 * {@code firstShownAt} is when it first made the board; {@code bumpedAt} when it left.
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
    boolean topPick,        // the single standout among the slate's picks (may be none)
    Double resultValue,
    Boolean won,
    boolean scored,
    boolean active,
    String firstShownAt,
    String bumpedAt,
    String bumpReason,       // 'lineup' | 'displaced' | null (see class doc)
    // Analyst promotion-gate verdict (V64) — what endorsed this pick onto the board.
    String debateVerdict,
    Double debateConfidence,
    String debateRationale
) {}
