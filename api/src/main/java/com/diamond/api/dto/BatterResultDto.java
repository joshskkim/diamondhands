package com.diamond.api.dto;

/** A batter's actual line for one finished game — used to grade prop-board picks. */
public record BatterResultDto(
    int playerId,
    long gameId,
    Integer atBats,
    Integer hits,
    Integer homeRuns,
    Integer strikeouts,
    Integer walks,
    // Total bases + runs/RBI grade the TB and H+R+RBI cards. runs/rbi are boxscore-only
    // (V69) so they can be null on Statcast-sourced rows.
    Integer totalBases,
    Integer runs,
    Integer rbi
) {}
