package com.diamond.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record PitcherDto(
    int id,
    String name,
    @JsonProperty("throws") String throws_
) {}
