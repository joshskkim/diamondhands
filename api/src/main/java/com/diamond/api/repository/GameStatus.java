package com.diamond.api.repository;

/**
 * Shared game-status helpers for board queries.
 *
 * <p>Mirrors the ingester's {@code _DEAD_GAME_STATUSES} (projection/runner.py): a game whose
 * {@code detailed_status} is one of these won't be played as scheduled, so the projector skips
 * it and its projection rows are cleared. These board queries add the same predicate as a
 * belt-and-suspenders so a dead game can never surface even if a re-project tick hasn't run
 * yet. {@code detailed_status} is NULL until the slate is built, so NULL counts as live.
 */
public final class GameStatus {

    private GameStatus() {}

    /** detailedState values for games that won't be played as scheduled. */
    public static final String DEAD_STATUSES = "'Postponed','Suspended','Cancelled'";

    /**
     * SQL predicate keeping only live (playable) games, for the {@code games} row aliased
     * {@code alias}. e.g. {@code livePredicate("g")} →
     * {@code (g.detailed_status IS NULL OR g.detailed_status NOT IN ('Postponed',...))}.
     */
    public static String livePredicate(String alias) {
        return "(" + alias + ".detailed_status IS NULL OR "
            + alias + ".detailed_status NOT IN (" + DEAD_STATUSES + "))";
    }
}
