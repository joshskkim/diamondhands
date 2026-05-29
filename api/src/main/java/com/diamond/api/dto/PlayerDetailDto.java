package com.diamond.api.dto;

public record PlayerDetailDto(
    int id,
    String fullName,
    Integer teamId,
    String teamAbbr,
    String position,
    String bats,
    String throwsHand
) {}
