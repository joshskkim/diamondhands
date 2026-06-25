package com.diamond.api.dto;

import java.time.LocalDate;
import java.util.List;

/**
 * The home board's current Model's Picks top set, posted so the server can record promptly
 * which earlier picks a better late play has displaced — without waiting for the nightly /
 * afternoon record-picks cron. {@code activeKeys} are in board (rank) order. {@code boardLoaded}
 * mirrors the ingester's guard: false (e.g. odds didn't load) is a no-op so an empty pull can
 * never wipe legitimately-shown picks; true with an empty {@code activeKeys} legitimately bumps
 * pre-game picks nothing qualifies for anymore.
 */
public record ReconcileRequest(LocalDate date, List<PickKey> activeKeys, boolean boardLoaded) {

    /** Identity of a pick, mirroring the ingester's _pick_key (line/price excluded). */
    public record PickKey(long gameId, String market, String side, Integer playerId) {}
}
