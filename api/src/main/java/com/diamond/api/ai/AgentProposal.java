package com.diamond.api.ai;

import java.util.Map;

/**
 * A proposed write action the user must confirm before it executes (human-in-the-loop). The
 * language model only ever PROPOSES: a write tool returns one of these, the server streams it to
 * the UI with a signed token, and {@code POST /api/agent/confirm} replays the EXACT
 * {@code payload} server-side — no second model call, so the executed write can't drift from
 * what the user approved.
 *
 * @param action  one of: set_bankroll | save_recommendation | log_bet | set_line_alert
 * @param summary human-readable description shown on the confirm button
 * @param payload validated, ready-to-execute arguments (also what the signed token carries)
 */
public record AgentProposal(String action, String summary, Map<String, Object> payload) {}
