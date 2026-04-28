# Runbook: RAGAS Quality Regression

**Trigger:** `eval-nightly.yaml` workflow opens a GitHub issue with label `eval-failure`.
**Severity:** SEV-2 (answer quality degraded for real users).
**SLO impact:** No latency/error SLO impact, but quality SLO breached.

---

## Quality SLOs

| Metric | Threshold |
|---|---|
| Faithfulness | ≥ 0.75 |
| Answer Relevancy | ≥ 0.75 |
| Context Recall | ≥ 0.75 |

---

## Immediate triage (< 30 min)

1. **Open the nightly eval report artifact** — `ragas-nightly-<run-id>.json`.
   Which metric(s) failed? By how much?

2. **Check if a recent deploy caused the regression**:
   ```bash
   git log --oneline -10
   ```
   Correlate the failure timestamp with deploy timestamps.

3. **Run a small manual eval** against the specific failing questions:
   ```bash
   cd packages/eval
   uv run python -m eval.ragas_runner \
     --api-url https://api.anime-rag.example.com \
     --sample 10 \
     --report /tmp/quick.json
   ```

4. **Identify the failure pattern** using the report:
   - Faithfulness ↓ → model is hallucinating (not grounded in retrieved docs)
   - Answer Relevancy ↓ → model is going off-topic
   - Context Recall ↓ → retriever is missing relevant documents

---

## Common causes and fixes

### Faithfulness regression

The generator is hallucinating. Common causes:
- Prompt template changed in `packages/prompts/`
- LLM model version silently updated by provider
- Context window too small (documents truncated)

**Fix:** Revert the last prompt template change and re-eval:
```bash
git diff HEAD~1 packages/prompts/
git revert HEAD  # if prompt change is the cause
```

### Answer Relevancy regression

- Query rewriter is distorting intent
- System prompt changed to be too verbose / off-topic

**Fix:** Test the rewriter directly:
```bash
curl -s -X POST http://localhost:8000/api/v1/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "dark psychological thriller", "top_n": 3}' | jq .answer
```
Compare the answer against the expected ground truth in `golden_set.json`.

### Context Recall regression

The retriever is missing relevant docs. Common causes:
- Index corruption (re-run `REINDEX`)
- BM25 tsvector weights changed
- Cohere reranker API returning errors / bad scores

**Fix:**
```sql
-- Check index health
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
WHERE tablename = 'anime_embeddings';

-- Rebuild if needed
REINDEX INDEX CONCURRENTLY anime_embedding_idx;
REINDEX INDEX CONCURRENTLY anime_fts_idx;
```

---

## Escalation

If the regression persists after the above fixes and affects > 20 % of golden-set queries:
1. Pin the last known-good image tag in ArgoCD prod app.
2. Open a GitHub issue with the full RAGAS report attached.
3. Block the next deployment until the root cause is resolved and scores recover.
