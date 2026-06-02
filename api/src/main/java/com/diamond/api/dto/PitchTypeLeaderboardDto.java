package com.diamond.api.dto;

/**
 * One row of the pitch-type leaderboard: a batter playing today whose opposing
 * starter throws the selected pitch type significantly, ranked by the batter's
 * regressed xwOBA edge over the league baseline for that pitch.
 */
public record PitchTypeLeaderboardDto(
    LeaderboardPlayer player,
    PitcherDto opposingPitcher,
    Double pitchTypeUsage,
    Double batterXwoba,
    Double leagueXwoba,
    Double edge,
    Integer pitchesSeen
) {
    public record LeaderboardPlayer(int id, String name, String teamAbbr) {}
}
