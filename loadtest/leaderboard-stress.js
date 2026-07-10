import http from 'k6/http';
import { check } from 'k6';
import { Trend, Rate } from 'k6/metrics';

// Documents a pool-saturation finding the observability stack surfaced: the heavy
// pitch-type leaderboard CTE holds a JDBC connection long enough that, with the cache
// off (loadtest profile) and concurrency >= the HikariCP pool size (10), the pool is
// exhausted — requests block up to connection-timeout (5s) and 500 with
// "HikariPool-1 - Connection is not available". Watch the HikariCP panel in Grafana
// (active pinned at 10, pending climbing) while this runs.
//
// In production this query is cached (5-min TTL), so it doesn't saturate the pool there;
// this script intentionally removes that cushion to expose the underlying ceiling.

const BASE = __ENV.BASE_URL || 'http://host.docker.internal:8080';
const LABEL = __ENV.LABEL || 'leaderboard-stress';
const PITCHES = ['FF', 'SI', 'FC', 'SL', 'CU', 'CH', 'FS'];

const tLeader = new Trend('ep_leaderboard', true);
const errRate = new Rate('leaderboard_errors');

export const options = {
  scenarios: {
    stress: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '10s', target: 15 }, // push past the 10-connection pool
        { duration: '20s', target: 15 },
        { duration: '5s', target: 0 },
      ],
    },
  },
};

export default function () {
  const pitch = PITCHES[Math.floor(Math.random() * PITCHES.length)];
  const res = http.get(`${BASE}/api/leaderboards/pitch-type?pitch=${pitch}`);
  tLeader.add(res.timings.duration);
  errRate.add(res.status !== 200);
  check(res, { 'status is 200': (r) => r.status === 200 });
}

export function handleSummary(data) {
  const m = data.metrics;
  const lat = m.ep_leaderboard ? m.ep_leaderboard.values : null;
  const err = m.leaderboard_errors ? m.leaderboard_errors.values.rate : null;
  console.log(`\n=== ${LABEL} ===`);
  if (lat) console.log(`latency  avg=${lat.avg.toFixed(0)}ms p95=${lat['p(95)'].toFixed(0)}ms max=${lat.max.toFixed(0)}ms`);
  if (err !== null) console.log(`error rate (non-200, incl. pool timeouts): ${(err * 100).toFixed(1)}%`);
  return { [`/scripts/results/${LABEL}.json`]: JSON.stringify(data, null, 2) };
}
