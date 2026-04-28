/**
 * k6 full load test — ramp 0 → 20 VU over 10 min, hold 5 min, ramp down.
 *
 * SLOs under test:
 *   - p95 latency < 15 s  (recommend endpoint, live LLM call)
 *   - p95 latency < 500 ms (health endpoint)
 *   - error rate   < 1 %
 *   - cache hit rate tracked (informational)
 *
 * Usage:
 *   k6 run scripts/load_test/full.js
 *   k6 run --env API_URL=https://staging.example.com scripts/load_test/full.js
 *   k6 run --env BEARER_TOKEN=sk_test_... scripts/load_test/full.js
 *
 * Output:
 *   k6 run --out json=load_report.json scripts/load_test/full.js
 */

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

// ── Config ────────────────────────────────────────────────────────────────────
const API_URL      = __ENV.API_URL      || "http://localhost:8000";
const BEARER_TOKEN = __ENV.BEARER_TOKEN || "";

// ── Custom metrics ────────────────────────────────────────────────────────────
const cacheHits    = new Counter("rag_cache_hits");
const cacheMisses  = new Counter("rag_cache_misses");
const errorRate    = new Rate("rag_errors");
const recommendP95 = new Trend("rag_recommend_duration", true);

// ── Load profile ──────────────────────────────────────────────────────────────
export const options = {
  stages: [
    { duration: "2m",  target: 5  },  // warm-up ramp
    { duration: "3m",  target: 10 },  // mid ramp
    { duration: "3m",  target: 20 },  // peak ramp
    { duration: "5m",  target: 20 },  // hold at peak
    { duration: "2m",  target: 0  },  // ramp down
  ],
  thresholds: {
    // SLOs
    "http_req_duration{endpoint:recommend}":      ["p(95)<15000"],
    "http_req_duration{endpoint:health}":          ["p(95)<500"],
    "http_req_failed":                             ["rate<0.01"],
    // Custom
    "rag_recommend_duration":                      ["p(95)<15000"],
    "rag_errors":                                  ["rate<0.01"],
  },
};

// ── Representative query pool ─────────────────────────────────────────────────
const QUERIES = [
  { query: "Dark psychological thriller with moral ambiguity", top_n: 3 },
  { query: "Fast-paced action anime with incredible animation", top_n: 5 },
  { query: "Slow-burn romance with emotional depth",           top_n: 3 },
  { query: "Sci-fi anime set in space with political intrigue",top_n: 5 },
  { query: "Isekai where the protagonist builds a kingdom",    top_n: 3 },
  { query: "Slice of life anime that are relaxing",            top_n: 5 },
  { query: "Mecha anime with deep world-building",             top_n: 3 },
  { query: "Sports anime with underdog team rising to top",    top_n: 5 },
  { query: "Horror anime that are genuinely scary",            top_n: 3 },
  { query: "Comedy anime with absurdist humor",                top_n: 5 },
  { query: "Anime with complex villains",                      top_n: 3 },
  { query: "Detective anime with clever mysteries",            top_n: 5 },
  { query: "Cyberpunk anime in dystopian future cities",       top_n: 3 },
  { query: "Anime about music and bands",                      top_n: 5 },
  { query: "Post-apocalyptic anime with survival themes",      top_n: 3 },
];

function randomQuery() {
  return QUERIES[Math.floor(Math.random() * QUERIES.length)];
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function buildHeaders() {
  const h = { "Content-Type": "application/json" };
  if (BEARER_TOKEN) h["Authorization"] = `Bearer ${BEARER_TOKEN}`;
  return h;
}

// ── VU script ─────────────────────────────────────────────────────────────────
export default function () {
  const headers = buildHeaders();

  group("health", () => {
    const res = http.get(`${API_URL}/health`, { tags: { endpoint: "health" } });
    check(res, {
      "health 200":            (r) => r.status === 200,
      "health response < 500ms": (r) => r.timings.duration < 500,
    });
    errorRate.add(res.status !== 200);
  });

  sleep(0.5);

  group("recommend", () => {
    const q   = randomQuery();
    const res = http.post(
      `${API_URL}/api/v1/recommend`,
      JSON.stringify(q),
      { headers, tags: { endpoint: "recommend" } },
    );

    const ok = check(res, {
      "recommend 200":      (r) => r.status === 200,
      "has answer":         (r) => {
        try { return !!JSON.parse(r.body).answer; } catch { return false; }
      },
      "latency < 15s":      (r) => r.timings.duration < 15000,
    });

    errorRate.add(!ok);
    recommendP95.add(res.timings.duration);

    // Track cache hit rate (informational, not a hard threshold)
    if (res.status === 200) {
      try {
        const body = JSON.parse(res.body);
        if (body.cached) { cacheHits.add(1);  }
        else             { cacheMisses.add(1); }
      } catch { /* ignore parse error */ }
    }
  });

  // Paced to ~1 req/s per VU — at 20 VU = ~20 RPS peak
  sleep(Math.random() * 1 + 0.5);
}

// ── Teardown summary ──────────────────────────────────────────────────────────
export function handleSummary(data) {
  const dur  = data.metrics["rag_recommend_duration"];
  const errs = data.metrics["rag_errors"];

  const summary = {
    p50_ms:        dur  ? Math.round(dur.values.med)          : null,
    p95_ms:        dur  ? Math.round(dur.values["p(95)"])      : null,
    p99_ms:        dur  ? Math.round(dur.values["p(99)"])      : null,
    error_rate:    errs ? errs.values.rate.toFixed(4)          : null,
    cache_hits:    data.metrics["rag_cache_hits"]   ? data.metrics["rag_cache_hits"].values.count   : 0,
    cache_misses:  data.metrics["rag_cache_misses"] ? data.metrics["rag_cache_misses"].values.count : 0,
    slo_p95_pass:  dur  ? dur.values["p(95)"] < 15000          : false,
    slo_error_pass: errs ? errs.values.rate < 0.01             : false,
  };

  console.log("\n── Load Test Summary ──────────────────────────────────");
  console.log(`  p50 latency : ${summary.p50_ms} ms`);
  console.log(`  p95 latency : ${summary.p95_ms} ms   (SLO < 15 000 ms: ${summary.slo_p95_pass ? "✅ PASS" : "❌ FAIL"})`);
  console.log(`  p99 latency : ${summary.p99_ms} ms`);
  console.log(`  error rate  : ${summary.error_rate}   (SLO < 1 %: ${summary.slo_error_pass ? "✅ PASS" : "❌ FAIL"})`);
  console.log(`  cache hits  : ${summary.cache_hits} / ${summary.cache_hits + summary.cache_misses}`);
  console.log("───────────────────────────────────────────────────────\n");

  return {
    stdout: JSON.stringify(summary, null, 2),
  };
}
