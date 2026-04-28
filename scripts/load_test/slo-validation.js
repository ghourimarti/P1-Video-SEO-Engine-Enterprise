/**
 * k6 SLO validation test — stepped ramp 0 → 20 VU with hard SLO thresholds.
 *
 * SLOs:
 *   p95 recommend latency  < 15 000 ms  (LLM call, cache miss)
 *   p95 stream TTFB        < 3 000 ms   (time to first SSE token)
 *   p95 health latency     <    500 ms
 *   error rate             <   1 %
 *   budget 429 rate        <   0.5 %    (budget guard should rarely fire)
 *
 * Scenarios:
 *   health    — constant 5 VU throughout (baseline)
 *   recommend — stepped ramp 0→20 VU (main SLO)
 *   stream    — 2 VU constant (SSE streaming TTFB)
 *
 * Usage:
 *   k6 run scripts/load_test/slo-validation.js
 *   k6 run --env API_URL=https://dev.anime-rag.example.com \
 *          --env BEARER_TOKEN=<token> \
 *          --out json=slo_report.json \
 *          scripts/load_test/slo-validation.js
 */

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

// ── Config ────────────────────────────────────────────────────────────────────
const API_URL      = __ENV.API_URL      || "http://localhost:8000";
const BEARER_TOKEN = __ENV.BEARER_TOKEN || "";
const BASE         = `${API_URL}/api/v1`;

// ── Custom metrics ─────────────────────────────────────────────────────────────
const cacheHits      = new Counter("slo_cache_hits");
const cacheMisses    = new Counter("slo_cache_misses");
const budget429s     = new Counter("slo_budget_429");
const errorRate      = new Rate("slo_errors");
const budget429Rate  = new Rate("slo_budget_429_rate");
const recommendDur   = new Trend("slo_recommend_ms",  true);
const streamTTFB     = new Trend("slo_stream_ttfb_ms", true);

// ── Scenarios + load profile ──────────────────────────────────────────────────
export const options = {
  scenarios: {
    health_baseline: {
      executor:    "constant-vus",
      vus:         5,
      duration:    "15m",
      exec:        "healthScenario",
      tags:        { scenario: "health" },
    },
    recommend_ramp: {
      executor:    "ramping-vus",
      startVUs:    0,
      stages: [
        { duration: "2m",  target: 5  },  // warm-up
        { duration: "3m",  target: 10 },  // mid
        { duration: "3m",  target: 20 },  // peak
        { duration: "5m",  target: 20 },  // hold
        { duration: "2m",  target: 0  },  // cool-down
      ],
      exec:        "recommendScenario",
      tags:        { scenario: "recommend" },
    },
    stream_constant: {
      executor:    "constant-vus",
      vus:         2,
      startTime:   "4m",   // start after warm-up completes
      duration:    "9m",
      exec:        "streamScenario",
      tags:        { scenario: "stream" },
    },
  },

  thresholds: {
    // ── Hard SLOs (CI fails if any breach) ──────────────────────────────────
    "http_req_duration{scenario:health}":    ["p(95)<500"],
    "http_req_duration{scenario:recommend}": ["p(95)<15000"],
    "http_req_failed":                        ["rate<0.01"],
    // Custom metric thresholds
    "slo_recommend_ms":                       ["p(95)<15000"],
    "slo_stream_ttfb_ms":                     ["p(95)<3000"],
    "slo_errors":                             ["rate<0.01"],
    "slo_budget_429_rate":                    ["rate<0.005"],
  },
};

// ── Query pool ────────────────────────────────────────────────────────────────
const QUERIES = [
  { query: "Dark psychological thriller with moral ambiguity", top_n: 3 },
  { query: "Fast-paced action anime with incredible animation", top_n: 5 },
  { query: "Slow-burn romance with emotional depth",           top_n: 3 },
  { query: "Sci-fi anime with political intrigue in space",    top_n: 5 },
  { query: "Isekai where the protagonist builds a kingdom",    top_n: 3 },
  { query: "Slice of life anime that are relaxing",            top_n: 5 },
  { query: "Mecha anime with deep world-building",             top_n: 3 },
  { query: "Sports anime with underdog team rising to top",    top_n: 5 },
  { query: "Horror anime that are genuinely scary",            top_n: 3 },
  { query: "Comedy anime with absurdist humor",                top_n: 5 },
  { query: "Anime with complex villains and moral grey areas", top_n: 3 },
  { query: "Detective anime with clever mysteries",            top_n: 5 },
  { query: "Cyberpunk anime in dystopian future cities",       top_n: 3 },
  { query: "Anime about music bands and artistic passion",     top_n: 5 },
  { query: "Post-apocalyptic survival anime",                  top_n: 3 },
];

function randomQuery() {
  return QUERIES[Math.floor(Math.random() * QUERIES.length)];
}

function headers() {
  const h = { "Content-Type": "application/json" };
  if (BEARER_TOKEN) h["Authorization"] = `Bearer ${BEARER_TOKEN}`;
  return h;
}

// ── Scenario: health ──────────────────────────────────────────────────────────
export function healthScenario() {
  const res = http.get(`${API_URL}/health`, { tags: { endpoint: "health" } });
  check(res, {
    "health 200":       (r) => r.status === 200,
    "health body ok":   (r) => r.body.includes("ok") || r.body.includes("healthy"),
    "health < 500ms":   (r) => r.timings.duration < 500,
  });
  errorRate.add(res.status !== 200);
  sleep(1);
}

// ── Scenario: recommend (non-streaming) ───────────────────────────────────────
export function recommendScenario() {
  const q   = randomQuery();
  const res = http.post(
    `${BASE}/recommend`,
    JSON.stringify(q),
    { headers: headers(), tags: { endpoint: "recommend" } },
  );

  // 429 = budget exhausted — tracked separately, not as error
  const is429 = res.status === 429;
  budget429Rate.add(is429);
  if (is429) {
    budget429s.add(1);
    sleep(2);
    return;
  }

  const ok = check(res, {
    "recommend 200":   (r) => r.status === 200,
    "has answer":      (r) => { try { return !!JSON.parse(r.body).answer; } catch { return false; } },
    "latency < 15s":   (r) => r.timings.duration < 15000,
  });

  errorRate.add(res.status >= 400 && res.status !== 429);
  recommendDur.add(res.timings.duration);

  if (res.status === 200) {
    try {
      const body = JSON.parse(res.body);
      body.cached ? cacheHits.add(1) : cacheMisses.add(1);
    } catch { /* ignore */ }
  }

  sleep(Math.random() * 1.5 + 0.5);
}

// ── Scenario: stream TTFB ─────────────────────────────────────────────────────
export function streamScenario() {
  const q   = randomQuery();
  const t0  = Date.now();

  const res = http.post(
    `${BASE}/recommend/stream`,
    JSON.stringify(q),
    {
      headers: headers(),
      tags:    { endpoint: "stream" },
      // k6 does not natively stream SSE — we measure response start time
      // as a proxy for TTFB (first event received)
      timeout: "30s",
    },
  );

  const ttfb = Date.now() - t0;

  const ok = check(res, {
    "stream 200":      (r) => r.status === 200,
    "has data event":  (r) => r.body.includes("data:"),
    "TTFB < 3s":       () => ttfb < 3000,
  });

  errorRate.add(!ok && res.status !== 429);
  streamTTFB.add(ttfb);

  sleep(3);
}

// ── Summary report ────────────────────────────────────────────────────────────
export function handleSummary(data) {
  const rec   = data.metrics["slo_recommend_ms"];
  const ttfb  = data.metrics["slo_stream_ttfb_ms"];
  const errs  = data.metrics["slo_errors"];
  const hits  = data.metrics["slo_cache_hits"];
  const total = (hits ? hits.values.count : 0)
              + (data.metrics["slo_cache_misses"] ? data.metrics["slo_cache_misses"].values.count : 0);

  const fmt = (v, unit="ms") => v != null ? `${Math.round(v)} ${unit}` : "n/a";
  const slo = (val, threshold, label) =>
    `${label}: ${fmt(val)}  (threshold ${threshold} — ${val != null && val < threshold ? "✅ PASS" : "❌ FAIL"})`;

  console.log("\n═══════ SLO Validation Report ═══════");
  console.log(slo(rec  ? rec.values["p(95)"]  : null, 15000, "p95 recommend "));
  console.log(slo(ttfb ? ttfb.values["p(95)"] : null,  3000, "p95 stream TTFB"));
  console.log(`error rate  : ${errs ? (errs.values.rate * 100).toFixed(2) : "n/a"} %  (SLO < 1 %)`);
  console.log(`cache hits  : ${hits ? hits.values.count : 0} / ${total} (${total > 0 ? ((hits ? hits.values.count : 0) / total * 100).toFixed(1) : 0} %)`);
  console.log(`budget 429s : ${data.metrics["slo_budget_429"] ? data.metrics["slo_budget_429"].values.count : 0}`);
  console.log("═════════════════════════════════════\n");

  return {
    "slo_report.json": JSON.stringify({
      p95_recommend_ms: rec  ? Math.round(rec.values["p(95)"])  : null,
      p95_stream_ttfb_ms: ttfb ? Math.round(ttfb.values["p(95)"]) : null,
      p50_recommend_ms: rec  ? Math.round(rec.values.med)       : null,
      error_rate:       errs ? errs.values.rate                 : null,
      cache_hits:       hits ? hits.values.count                : 0,
      cache_total:      total,
      slo_p95_pass:     rec  ? rec.values["p(95)"] < 15000      : false,
      slo_ttfb_pass:    ttfb ? ttfb.values["p(95)"] < 3000      : false,
      slo_error_pass:   errs ? errs.values.rate < 0.01          : false,
    }, null, 2),
  };
}
