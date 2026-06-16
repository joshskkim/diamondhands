package com.diamond.api.dto;

public record TennisPlayerDto(
    String id,
    String name,
    String country,
    Integer age,
    String hand
) {}
