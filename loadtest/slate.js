import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

// Drives the heavy read endpoints concurrently. Run the API under the `loadtest`
// Spring profile (cache disabled) so this measures the real service + DB path and
// HikariCP pool contention — exactly the surface the N+1 fixes target.

const BASE = __ENV.BASE_URL || 'http://host.docker.internal:8080';
const GAME_ID = __ENV.GAME_ID || '823368';
const LABEL = __ENV.LABEL || 'run';

const tProps = new Trend('ep_props_board', true);
const tProj = new Trend('ep_projections', true);
const tBest = new Trend('ep_odds_best', true);

export const options = {
  scenarios: {
    slate: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '15s', target: 10 }, // ramp to 10 concurrent users
        { duration: '30s', target: 10 }, // hold
        { duration: '5s', target: 0 },   // ramp down
      ],
      gracefulStop: '5s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    ep_props_board: ['p(95)<3000'],
    ep_projections: ['p(95)<3000'],
  },
};

function hit(path, trend) {
  const res = http.get(`${BASE}${path}`, { tags: { endpoint: path } });
  trend.add(res.timings.duration);
  check(res, { 'status is 200': (r) => r.status === 200 });
}

// The N+1 fix targets: prop board (~33 queries/req) and projections (~37/req).
// odds/best is included as a light comparison endpoint. The heavy leaderboard CTE is
// exercised separately by leaderboard-stress.js — its connection-hold time saturates
// the pool and would otherwise mask the N+1 signal here.
export default function () {
  hit('/api/props/board', tProps);
  hit(`/api/games/${GAME_ID}/projections`, tProj);
  hit('/api/odds/best', tBest);
}

export function handleSummary(data) {
  const out = {};
  out[`/scripts/results/${LABEL}.json`] = JSON.stringify(data, null, 2);
  // Also echo a compact table to the console.
  const pick = (m) => {
    const v = data.metrics[m];
    if (!v) return 'n/a';
    return `avg=${v.values.avg.toFixed(0)}ms p95=${v.values['p(95)'].toFixed(0)}ms`;
  };
  console.log(`\n=== ${LABEL} ===`);
  console.log(`props/board   ${pick('ep_props_board')}`);
  console.log(`projections   ${pick('ep_projections')}`);
  console.log(`odds/best     ${pick('ep_odds_best')}`);
  return out;
}
