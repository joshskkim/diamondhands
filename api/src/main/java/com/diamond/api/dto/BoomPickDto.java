package com.diamond.api.dto;

import java.util.List;

/**
 * The "Lotto of the Day" — a single home-run boom pick (GET /api/lotto). Unlike the
 * Best Lines board, this is NOT chosen on price/edge: it surfaces a hitter the slate is
 * sleeping on — batting in the bottom of the order, recently cold, but with genuine raw
 * power (barrels + ISO) — in a park / pitcher / weather setup that amplifies home runs
 * today. The selection is deliberately age-blind: nothing here reads birth date or
 * service time, so a slumping veteran and a hot rookie are weighed on the same footing.
 *
 * <p>The implied wager is always HR over 0.5 (to hit a homer). {@code priceAmerican} /
 * {@code priceDecimal} / {@code bestBook} are the best HR-over price across books and are
 * null when no book has posted it yet — the pick still stands on the model. {@code reasons}
 * are server-built so the card and the recorded pick read identically.
 */
public record BoomPickDto(
    long gameId,
    String matchup,
    int playerId,
    String playerName,
    String bats,
    boolean isHome,
    int lineupPosition,
    String opposingPitcher,
    // the model's HR probability (shown for context, NOT a selection gate)
    double pHr,
    // historical "chops": season raw-power markers, age-blind
    double barrelRate,
    double isoSeason,
    // the cold signal: recent form below true talent (season − last-30)
    Double xwoba,
    Double xwobaL30,
    double coldGap,
    // today's HR amplification (the "esp. matchup/park" part)
    double adjPark,
    double adjPitcher,
    double adjWeatherHr,
    double condBoost,
    // projected carry in this park/weather, null when no HR-distance sample
    Double hrDistanceFt,
    // best HR-over 0.5 price across books — null when not yet posted (pick stands regardless)
    Integer priceAmerican,
    Double priceDecimal,
    String bestBook,
    double boomScore,
    List<String> reasons
) {}
