package com.diamond.api.dto;

public record TennisRankingDto(
    int rank,
    TennisPlayerDto player,
    Double elo,
    Double serveSkill,      // SPW; null when no serve data on the surface
    Double returnSkill,     // RPW
    Integer matches
) {}
