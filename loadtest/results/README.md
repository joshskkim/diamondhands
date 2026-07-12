# Load-test result artifacts

Raw `handleSummary` output from k6. Two of these are an **archived pair** documenting the
leaderboard pool-saturation fix, and cannot be regenerated on the current dev DB — see below.

| file | script | produced by |
|---|---|---|
| `leaderboard-before.json` | `leaderboard-stress.js` | `30c05cc` (fix not yet applied) |
| `leaderboard-after.json` | `leaderboard-stress.js` | `5423ea4` (fix applied) |
| `before.json` / `after.json` | `slate.js` | N+1 fixes, see `docs/observability-and-perf.md` §2 |

## The leaderboard pair

Both runs: `loadtest` Spring profile (Redis cache off), 15 VUs against
`/api/leaderboards/pitch-type`.

| | before | after |
|---|---|---|
| avg | 15,009 ms | 2,505 ms |
| p95 | 60,001 ms | 7,792 ms |
| error rate | 100% | 0% |
| checks passed | 0 / 27 | 175 / 175 |

The `after` p95 is still seconds because the cache is off: the single-flight peer-check in
`LeaderboardService` can never hit a no-op cache, so every lock waiter recomputes and requests
queue per key instead of exhausting the pool. That is lock serialization, not a residual bug —
with the cache on (production) the same burst collapses to one query.

## Why these are not reproducible

The meltdown was driven by the `DISTINCT ON` snapshot CTEs scanning the *entire* history of two
tables. Those tables have since been stripped to the current season:

| table | at capture (Jun 2026) | today |
|---|---|---|
| `pitcher_arsenal` | ~444,000 | ~59,000 |
| `batter_pitch_type_stats` | ~509,000 | ~65,000 |

At ~13% of the original row count, even the *unfixed* query is far off its ~98 s worst case. A
fresh run would produce a flattering number that does not compare against `leaderboard-before.json`.
Treat this pair as archival evidence. The behavior the fix actually guarantees — one DB query per
key under a concurrent cold burst — is pinned by `LeaderboardServiceTest` instead, which is
independent of DB size and runs in CI.
