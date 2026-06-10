package com.diamond.api.dto;

/** One bookmaker's posted price for a prop selection (American + decimal). */
public record BookQuoteDto(
    String book,
    int priceAmerican,
    double priceDecimal
) {}
