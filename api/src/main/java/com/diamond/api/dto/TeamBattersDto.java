package com.diamond.api.dto;

import java.util.List;

public record TeamBattersDto(String teamAbbr, List<BatterProjectionDto> batters) {}
