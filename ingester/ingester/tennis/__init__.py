"""Tennis (ATP) projection pipeline — parallel to the MLB `projection` package.

Model shape: surface-blended dynamic Elo (match-winner prior) + opponent-adjusted
serve/return point model -> hierarchical match simulator (game/set/match win prob,
expected games), Bo3/Bo5-aware. Data source: Jeff Sackmann's tennis_atp dataset
(CC BY-NC-SA, non-commercial).
"""
