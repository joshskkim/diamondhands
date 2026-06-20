# Observability & Performance Engineering

This document describes the observability stack added to the Diamond API and the
data-driven performance work it enabled: **instrument → observe → find the bottleneck
with data → fix it → prove the improvement.**

## 1. Observability stack

The API (Spring Boot 3.3.6 / Java 21) was previously operationally blind — no metrics,
no tracing, plain-text logs, a static `/health`. Added:

| Concern | Implementation |
|---|---|
| **Metrics** | Spring Boot Actuator + Micrometer + Prometheus registry. `http.server.requests` with server-side percentile histograms (true p50/p95/p99), HikariCP pool, JVM heap/GC, and per-service `@Observed` timers. Exposed at `/actuator/prometheus`. |
| **Business metrics** | `BusinessMetrics` registers product gauges refreshed on a 60s timer (cheap COUNTs + cached Stripe price lookups): `diamond_users`, `diamond_subscriptions_active` (Pro), `diamond_subscriptions_customers`, `diamond_mrr_usd` (monthly-recurring revenue, derived from each active sub's Stripe price interval). |
| **Dashboards** | Prometheus + Grafana in `docker-compose`, with provisioned dashboards (`monitoring/grafana/...`): **Diamond API — Observability** (request rate, latency percentiles by URI, error rate, **HikariCP active/idle/pending**, JVM) and **Diamond — Business** (users, Pro subscribers, MRR, free→paid conversion, signups). |
| **Tracing** | Micrometer Tracing → OpenTelemetry → OTLP → **Jaeger** (`docker-compose`). `datasource-micrometer` emits a span per JDBC query, so a request's DB fan-out shows up as a trace waterfall. 100% sampling in dev. |
| **Structured logging** | `logback-spring.xml` emits JSON (logstash encoder) with the active `traceId`/`spanId` from MDC, so a log line links to its trace. A `local` profile prints human-readable lines. |
| **Health** | `/actuator/health` with DB + Redis indicators and liveness/readiness groups (the legacy `/health` is kept for the frontend). |

### Running it
```bash
docker compose up -d                 # postgres, redis, flyway, prometheus, grafana, jaeger
cd api && JAVA_HOME=/opt/homebrew/opt/openjdk@21 mvn spring-boot:run
```
- Grafana: http://localhost:3001 (anonymous admin) — "Diamond API — Observability"
- Jaeger: http://localhost:16686 (service `diamond-api`)
- Prometheus: http://localhost:9090

## 2. Bottlenecks found — and fixed

The trace waterfalls in Jaeger immediately exposed two **N+1 query** patterns: a single
request fanning out into dozens of sequential `query` spans.

### Fix 1 — Prop board (`/api/props/board`)
`PropBoardService.board` called `findClearRates(playerId)` once per candidate (~30/req).
Replaced with a single `findClearRatesBatch(playerIds)` (`WHERE player_id = ANY(?)` +
`PARTITION BY player_id`), prefetched once before scoring.

### Fix 2 — Game projections (`/api/games/{id}/projections`)
`ProjectionService` issued 2 snapshot queries (arsenal + batter pitch stats) **per batter**
(~37/req). Replaced with two batched queries for the whole game, resolving each player's
point-in-time snapshot via a `DISTINCT ON` CTE (the pattern already proven on
`LEADERBOARD_SQL`). The arsenal league-baseline join intentionally reproduces the original's
per-pitcher-hand quirk so the response stays byte-identical.

### Fix 3 — Best plays (`/api/odds/best`)
`OddsService.bestPlays` looped over the slate's games calling `gameOdds(gameId)` (plus a
redundant meta lookup) — ~5 queries per game. Replaced with four date-scoped batch reads
(`find*ByDate` → `Map<gameId, …>`) and a shared `buildGameOdds(...)` builder, so the whole
slate costs a constant ~5 queries instead of ~5·N. A deterministic `bookmaker` tiebreaker was
added to the odds ordering so the batched and per-game results are exactly equal on price ties.

All fixes are **behavior-preserving** — `RepositoryBatchEquivalenceTest` asserts the batched
queries return results identical to N single-key calls against the live DB (clear rates,
arsenal/pitch stats, and the four odds reads over a real 15-game slate).

### Result (verified)

**Trace span count (Jaeger), single request:**

| Endpoint | `query` spans before | after |
|---|---|---|
| `/api/props/board` | 33 | **4** |
| `/api/games/{id}/projections` | 37 | **3** |
| `/api/odds/best` (15-game slate) | ~5·N ≈ 75 | **~5** (constant) |

**Load test (k6, 10 VUs, 50s, cache disabled to exercise the DB path):**

| Endpoint | metric | before | after | change |
|---|---|---|---|---|
| props/board | p95 | 39 ms | 25 ms | **−37%** |
| props/board | avg | 32 ms | 18 ms | −43% |
| projections | p95 | 33 ms | 14 ms | **−57%** |
| projections | avg | 26 ms | 9 ms | −64% |
| odds/best (control) | p95 | 2 ms | 5 ms | ~noise |

Throughput over the same window roughly **doubled** (6,607 → 13,364 completed iterations):
fewer per-request round-trips freed the connection pool to serve more concurrent work.

## 3. Leaderboard meltdown — root-caused and fixed

`leaderboard-stress.js` hammers `/api/leaderboards/pitch-type` (the heaviest query — a
multi-CTE snapshot join) with the cache off. At 15 concurrent VUs the **HikariCP pool (size
10) was exhausted**: `Connection is not available, request timed out after 5005ms`, latency
blew out to tens of seconds, **~100% errors** (Grafana HikariCP panel: `active` pinned at 10,
`pending` climbing).

Pulling the thread with `EXPLAIN` revealed the real cause: a **single execution of the
leaderboard query took ~98 s**. Two compounding problems:
1. The `DISTINCT ON` snapshot CTEs scanned the *entire* history of `pitcher_arsenal` (444k
   rows) and `batter_pitch_type_stats` (509k) — `as_of_date <= today` matches almost
   everything — and no index matched the `(player_id, vs_handedness, as_of_date DESC,
   season DESC)` ordering, so each query did a full sort inside nested loops.
2. The query resolved snapshots for **all ~4,000 players** before joining down to the ~30 on
   the slate.

Fixes (both behavior-preserving — pre-filtering a join input to the keys that survive the
join cannot change the result):
- **Index** matching the `DISTINCT ON` ordering on both snapshot tables (`V34`): 98 s → 11.7 s.
- **Restrict the snapshot CTEs to the slate's pitchers/batters** up front: 11.7 s → **~70 ms**.
- **Single-flight guard** (`LeaderboardService`): an explicit per-cache-key lock so concurrent
  cold misses run the heavy query *once* and the rest reuse the result. (`@Cacheable(sync=true)`
  is the declarative form but deadlocks with this RedisCacheManager.)

**Verified:**

| | before | after |
|---|---|---|
| Raw query (psql) | ~98 s | ~70 ms |
| Cold request (API) | (pool timeout / 500) | 0.26 s, then ~0.02 s cached |
| 20 concurrent cold requests | 20 DB computations, pool exhausted | **1 DB computation**, all 200, ~75 ms |
| Stress (cache off, 15 VUs) | ~100% errors, p95 60 s | **0% errors**, avg 2.5 s |

A `leaderboard.db.query` counter was added to make the single-flight effect directly
observable (it increments only on an actual heavy-query execution).

## 4. SLOs & alerting

`monitoring/alert-rules.yml` (loaded by Prometheus, firing alerts visible at
`http://localhost:9090/alerts`) encodes the service SLOs:

| Alert | Condition | SLO |
|---|---|---|
| `HighErrorRate` | 5xx ratio > 5% for 5m | availability < 1% errors |
| `HighRequestLatencyP95` | p95 `http.server.requests` > 1s for 5m | latency p95 < 1s |
| `HikariConnectionsWaiting` | `hikaricp_connections_pending` > 0 for 2m | no pool starvation |
| `HikariPoolExhausted` | `active >= max` for 1m | — (the leaderboard meltdown signature) |

The two HikariCP rules would have paged on the leaderboard meltdown before users saw timeouts.
Routing/paging would add an Alertmanager; the Prometheus Alerts tab is enough locally.

## 5. CI

`.github/workflows/api-ci.yml` runs on PRs touching `api/**` or `db/migrations/**`:
1. **Verify Flyway migrations apply from an empty database.** This caught (and now guards) a
   real main bug: two `V32__` files → `Found more than one migration with version 32`, which
   broke every fresh environment but was invisible to anyone with an already-populated dev DB.
   (Fixed by renumbering one to `V32_1`.)
2. **Build & test** (`mvn -B verify`) against Postgres + Redis service containers, so the
   `@SpringBootTest` integration tests exercise real datasource/redis wiring. The
   data-dependent equivalence assertions `assumeTrue`-skip on an empty CI database; the unit
   tests and context/health checks run fully.

## Reproducing the measurements
```bash
# under the loadtest profile (cache off) so the DB path is actually exercised:
cd api && mvn spring-boot:run -Dspring-boot.run.profiles=loadtest
cd loadtest && ./run.sh before   # (on the pre-fix commit) then ./run.sh after
docker exec diamond-redis redis-cli flushall   # between runs, cold cache
```
Span counts: flush Redis, hit the endpoint once on the **default** profile (100% sampling),
read the trace in Jaeger.
