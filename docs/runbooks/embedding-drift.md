# Runbook: Embedding Drift Alert

**Trigger:** `model-drift.yaml` workflow fails — mean cosine distance > 0.12 threshold.
**Severity:** SEV-3 (quality degradation, no immediate outage).
**SLO impact:** None directly, but signals retrieval quality is degrading.

---

## What this means

The embedding drift detector compares the mean cosine distance between:
- **Golden set embeddings** — the 100 curated representative queries embedded with
  `text-embedding-3-large`.
- **Recent production queries** — sampled from `audit_log` (last 7 days).

A distance > 0.12 means production queries have drifted away from the distribution
the system was designed for. Retrieval quality is likely degraded.

---

## Immediate triage (< 15 min)

1. **Read the drift report artifact** from the failed GitHub Actions run.
   Look at `mean_cosine_distance` and `n_production_queries`.

2. **Sample recent production queries** from audit_log:
   ```sql
   SELECT query, created_at
   FROM audit_log
   WHERE created_at >= NOW() - INTERVAL '7 days'
     AND guard_blocked = false
   ORDER BY created_at DESC
   LIMIT 50;
   ```
   Are the queries about new topic areas not covered by the golden set?

3. **Check RAGAS scores** — did the nightly eval also degrade?
   Look at recent `ragas-nightly` workflow runs in GitHub Actions.
   If both drift AND RAGAS scores are degraded, the problem is real.

4. **Check if new content was ingested** — new anime titles in the corpus can shift
   the embedding space. This is intentional drift, not a problem.
   ```sql
   SELECT COUNT(*), MAX(ingested_at) FROM anime_embeddings;
   ```

---

## Remediation

### If drift is due to new content (benign)

Update the golden set to include representative queries for the new content:
```bash
# Add new entries to packages/eval/golden/golden_set.json
# Then re-embed the golden set baseline:
cd packages/eval
uv run python -m eval.drift_detector --update-baseline
```

### If drift is due to user query shift (new topic domain)

1. Add new anime in the new topic area to the corpus via `scripts/ingest.py`.
2. Update the golden set with representative queries from the new domain.
3. Re-run RAGAS eval on the new golden set to verify quality.

### If drift is unexplained (possible model change)

Check if the embedding model was updated:
```python
# Verify model used in production
import litellm
litellm.embedding("text-embedding-3-large", input=["test"])
```
If OpenAI silently updated the model, re-embed the entire corpus:
```bash
uv run python scripts/ingest.py --csv data/anime_with_synopsis.csv --re-embed
```

---

## False positive criteria

Close the alert without action if ALL of:
- `n_production_queries` < 50 (insufficient sample)
- New content was recently ingested (corpus expansion)
- RAGAS nightly scores are still ≥ 0.75 on all metrics
