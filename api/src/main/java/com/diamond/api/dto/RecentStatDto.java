package com.diamond.api.dto;

public record RecentStatDto(
    String gameDate,
    String opp,
    boolean isHome,
    Integer pa,
    Integer hits,
    Integer hr,
    Integer k,
    Double xwoba
) {}
