# Runbook: High Recommend Latency

**Trigger:** p95 recommend latency > 15 000 ms sustained for 2 minutes.
**Severity:** SEV-2 (user-facing degradation, not full outage).
**SLO impact:** Breaks the 15 s p95 SLO.

---

## Immediate triage (< 5 min)

1. **Check Grafana** — open the SLO dashboard, confirm which percentile is elevated.
   ```
   Dashboard: Anime RAG — SLO Dashboard → "Recommend Latency Percentiles"
   ```
2. **Is it the LLM or the retrieval layer?**
   Check the `rag.pipeline` OTel span breakdown in Langfuse:
   - `rewrite` slow → query rewriter LLM call throttled
   - `retrieve` slow → pgvector / BM25 index issue or connection pool saturation
   - `generate` slow → primary LLM provider throttled or slow

3. **Activate kill switch** (routes all traffic to cheaper/faster Haiku):
   ```bash
   curl -s -X POST https://api.anime-rag.example.com/api/v1/admin/cost/kill-switch \
     -H "Content-Type: application/json" \
     -d '{"active": true, "reason": "high latency mitigation"}'
   ```
   Kill switch reduces generation latency significantly since Haiku is 3–4× faster.

4. **Check DB connection pool** — if PgBouncer waiting queue > 5:
   ```sql
   SELECT * FROM pgbouncer.pools WHERE database = 'anime_rag';
   ```
   If `cl_waiting > 5`, the pool is saturated. Increase `default_pool_size` in
   `infra/pgbouncer/pgbouncer.ini` and reload:
   ```bash
   kubectl exec -n anime-rag-prod deploy/pgbouncer -- psql -h /tmp -U pgbouncer -c "RELOAD"
   ```

---

## Common causes and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| `generate` span slow, all requests | LLM provider throttled | Activate kill switch; LiteLLM falls back to Groq |
| `retrieve` span slow | pgvector index missing or dead rows | `REINDEX INDEX CONCURRENTLY anime_embedding_idx;` |
| All spans slow, high CPU | Node CPU saturation | Karpenter should scale; check `kubectl top nodes` |
| Cache miss rate spiked | Redis eviction (memory pressure) | `redis-cli INFO memory` — increase `maxmemory` or flush stale keys |
| Latency returns to normal | Transient provider blip | Deactivate kill switch after p95 stable for 5 min |

---

## Deactivate kill switch (after recovery)

```bash
curl -s -X POST https://api.anime-rag.example.com/api/v1/admin/cost/kill-switch \
  -H "Content-Type: application/json" \
  -d '{"active": false, "reason": "latency recovered, returning to normal routing"}'
```

Verify p95 remains < 15 000 ms for 5 minutes before declaring recovery.

---

## Post-incident

1. Write a postmortem capturing: timeline, root cause, customer impact duration, fix.
2. If LLM provider was the cause, consider adding a second provider to LiteLLM fallback chain.
3. If pool saturation was the cause, raise `default_pool_size` permanently and update
   `values-prod.yaml` accordingly.
