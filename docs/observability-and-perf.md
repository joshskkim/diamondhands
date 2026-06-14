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
| **Dashboards** | Prometheus + Grafana in `docker-compose`, with a provisioned dashboard (`monitoring/grafana/...`): request rate, latency percentiles by URI, error rate, **HikariCP active/idle/pending**, JVM. |
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

Both fixes are **behavior-preserving** — `RepositoryBatchEquivalenceTest` asserts the batched
queries return results identical to N single-key calls against the live DB.

### Result (verified)

**Trace span count (Jaeger), single request:**

| Endpoint | `query` spans before | after |
|---|---|---|
| `/api/props/board` | 33 | **4** |
| `/api/games/{id}/projections` | 37 | **3** |

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

## 3. Bottleneck found — documented (cache is load-bearing)

`leaderboard-stress.js` hammers `/api/leaderboards/pitch-type` (the heaviest query — a
multi-CTE snapshot join) with the cache off. At 15 concurrent VUs the **HikariCP pool (size
10) is exhausted**: `Connection is not available, request timed out after 5005ms`, latency
blows out to tens of seconds, ~100% errors. The Grafana HikariCP panel shows `active` pinned
at 10 with `pending` climbing.

In production the 5-minute Redis cache masks this, but it's a latent scaling cliff (cold-cache
deploys, cache-stampede on TTL expiry). Candidate mitigations, in order of preference:
materialize/precompute the leaderboard, add cache-stampede protection (single-flight), or size
the pool to the workload. Tracked as identified-not-yet-fixed.

## Reproducing the measurements
```bash
# under the loadtest profile (cache off) so the DB path is actually exercised:
cd api && mvn spring-boot:run -Dspring-boot.run.profiles=loadtest
cd loadtest && ./run.sh before   # (on the pre-fix commit) then ./run.sh after
docker exec diamond-redis redis-cli flushall   # between runs, cold cache
```
Span counts: flush Redis, hit the endpoint once on the **default** profile (100% sampling),
read the trace in Jaeger.
