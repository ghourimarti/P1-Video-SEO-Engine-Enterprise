// k6 smoke test — validates the API is alive under minimal load.
// Full ramp (0→20 VU, p95 < 15s) implemented in M8.
//
// Usage: k6 run scripts/load_test/smoke.js
//        k6 run --env API_URL=http://localhost:8000 scripts/load_test/smoke.js

import http from "k6/http";
import { check, sleep } from "k6";

const API_URL = __ENV.API_URL || "http://localhost:8000";

export const options = {
  vus: 1,
  duration: "30s",
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<5000"],
  },
};

export default function () {
  // Health check
  const health = http.get(`${API_URL}/health`);
  check(health, { "health 200": (r) => r.status === 200 });

  // Recommend endpoint (stub — returns 200 with placeholder text)
  const payload = JSON.stringify({ query: "action anime with great animation", top_n: 3 });
  const params = { headers: { "Content-Type": "application/json" } };
  const rec = http.post(`${API_URL}/api/v1/recommend`, payload, params);
  check(rec, {
    "recommend 200": (r) => r.status === 200,
    "has answer field": (r) => JSON.parse(r.body).answer !== undefined,
  });

  sleep(1);
}
