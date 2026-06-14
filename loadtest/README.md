# Load testing (k6)

Drives the heavy read endpoints under concurrency to surface — and then verify the fix of —
the N+1 query bottlenecks. Uses the `grafana/k6` Docker image (no local k6 install needed).

## Run the API in load-test mode

The `loadtest` Spring profile disables the Redis cache so every request hits the real
service + DB path (otherwise you'd mostly measure cache latency):

```bash
cd api
JAVA_HOME=/opt/homebrew/opt/openjdk@21 \
  mvn spring-boot:run -Dspring-boot.run.profiles=loadtest
```

## Capture before / after

```bash
cd loadtest
./run.sh before     # baseline (N+1 present)
# ... apply the fixes, restart the API ...
./run.sh after      # post-fix
```

Each run writes `results/<label>.json` and prints a compact avg/p95 table per endpoint.

## What to look at
- **k6 console table** + `results/*.json`: avg/p95 per endpoint, before vs after.
- **Grafana** (`http://localhost:3001`): p95-by-URI and HikariCP active/pending panels —
  the N+1 saturates the 10-connection pool under load; the fix relieves it.
- **Jaeger** (`http://localhost:16686`): trace waterfall for `/api/props/board` shows the
  per-request `query` span count collapse (≈33 → ≈3).
