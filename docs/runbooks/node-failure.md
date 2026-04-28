# Runbook: Node Failure / Cluster Recovery

**Trigger:** Node becomes NotReady, Pods in Pending/CrashLoopBackOff, or Karpenter
cannot provision a replacement within 5 minutes.
**Severity:** SEV-1 if all API replicas lost; SEV-2 if one replica lost.

---

## Immediate triage (< 5 min)

1. **Check node status**:
   ```bash
   kubectl get nodes -o wide
   kubectl describe node <node-name>
   ```
   Look for: `MemoryPressure`, `DiskPressure`, `NetworkUnavailable`, or EC2 termination.

2. **Check Karpenter provisioner status**:
   ```bash
   kubectl get nodeclaims -A
   kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=50
   ```
   Karpenter should automatically provision a replacement node within 2–3 minutes.

3. **Check pod status**:
   ```bash
   kubectl get pods -n anime-rag-prod -o wide
   kubectl describe pod <pod-name> -n anime-rag-prod
   ```

---

## If Karpenter is not provisioning

Check if the EC2 service limit is reached or Spot capacity is unavailable:
```bash
# Check Karpenter for capacity errors
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter | grep -i "insufficient\|capacity\|error"
```

If Spot unavailable, the NodePool falls back to On-Demand for nodes matching the
same instance family. If all fall back:
```bash
# Temporarily widen instance types to find available capacity
kubectl edit nodepool default
# Add m5.4xlarge, c5.2xlarge, r5.large to the requirements list
```

---

## If pods are CrashLoopBackOff

```bash
kubectl logs <pod-name> -n anime-rag-prod --previous
```

Common causes:
| Error | Fix |
|---|---|
| `OPENAI_API_KEY not set` | ESO secret failed to sync — check ExternalSecret status |
| `Connection refused` (DB) | PgBouncer not ready; wait or `kubectl rollout restart` |
| `OOMKilled` | Increase memory limit in `values-prod.yaml` |
| Image pull error | ECR auth expired; check IRSA role on the node |

---

## If ESO secrets failed to sync

```bash
kubectl get externalsecret -n anime-rag-prod
kubectl describe externalsecret anime-rag-api-secrets -n anime-rag-prod
```

If the secret store cannot reach AWS Secrets Manager:
1. Verify IRSA role ARN annotation on the `anime-rag-api` service account.
2. Check the OIDC provider is still valid: `aws iam list-open-id-connect-providers`.
3. Force a refresh: `kubectl annotate externalsecret anime-rag-api-secrets force-sync=$(date +%s) -n anime-rag-prod`.

---

## Manual rollback

If the failure was caused by a bad deploy:
```bash
# Abort canary and roll back
kubectl argo rollouts abort anime-rag-api -n anime-rag-prod
kubectl argo rollouts undo anime-rag-api -n anime-rag-prod

# Verify rollback is healthy
kubectl argo rollouts status anime-rag-api -n anime-rag-prod
```

---

## Post-incident

1. Check AWS EC2 console for the terminated/failed instance — capture the termination reason.
2. If Spot interruption: add more instance type diversity to the Karpenter NodePool.
3. If OOM: profile the API under load and adjust resource limits.
4. Verify the PodDisruptionBudget (`minAvailable: 1`) prevented a full outage.
5. Write a postmortem: timeline, blast radius, MTTR, preventive actions.
