# Runbook: Budget Exhausted (429 Spike)

**Trigger:** `slo_budget_429_rate > 0.5 %` or global daily budget exhausted alert.
**Severity:** SEV-2 if global budget; SEV-3 if single user.
**SLO impact:** Legitimate users receive 429 errors.

---

## Immediate triage (< 5 min)

1. **Identify scope** — single user or global?
   ```bash
   # Today's cost summary
   curl -s https://api.anime-rag.example.com/api/v1/admin/cost/summary | jq .
   ```
   Look at `total_usd`. If it is near or above `global_daily_budget_usd` (default $50),
   the global limit is the problem.

2. **Check audit_log for unusual traffic**:
   ```sql
   SELECT user_id, COUNT(*) AS reqs, ROUND(SUM(cost_usd)::numeric,4) AS cost
   FROM audit_log
   WHERE created_at >= CURRENT_DATE
   GROUP BY user_id
   ORDER BY cost DESC
   LIMIT 20;
   ```

3. **Identify if traffic is legitimate or abusive**:
   - Legitimate spike (marketing campaign, feature launch): raise global budget temporarily.
   - Single user over-spending: check if they are a known customer or a bad actor.
   - Automated/bot traffic: check `guard_blocked` ratio in audit_log.

---

## Remediation options

### A — Raise global daily budget (temporary)

Update the env var and restart API:
```bash
kubectl set env deployment/anime-rag-api \
  GLOBAL_DAILY_BUDGET_USD=100.00 \
  -n anime-rag-prod
```
Revert same day once traffic normalises.

### B — Per-user rate limit (abusive single user)

The user's key in Redis is `cost:budget:user:<user_id>:<YYYY-MM-DD>`.
To manually cap a specific user at their current spend (effectively blocking further requests today):
```bash
# Get current TTL and set the key to the limit value
redis-cli SET "cost:budget:user:<user_id>:$(date -u +%Y-%m-%d)" 9999.0 KEEPTTL
```

### C — Activate kill switch (reduce per-request cost)

If the issue is cost efficiency rather than hard budget:
```bash
curl -s -X POST https://api.anime-rag.example.com/api/v1/admin/cost/kill-switch \
  -H "Content-Type: application/json" \
  -d '{"active": true, "reason": "global budget approaching limit — routing to cheap model"}'
```
Haiku costs ~15× less per token than Sonnet, extending budget significantly.

---

## Post-incident

1. Review whether the default budget limits are appropriate for current traffic volume.
2. If a single user caused the global budget to exhaust, consider per-user rate limiting
   at the API gateway level rather than just the Redis budget guard.
3. If a legitimate traffic spike caused it, add auto-scaling budget based on replica count.
