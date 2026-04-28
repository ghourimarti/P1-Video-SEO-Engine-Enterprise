# Helm Charts

Implemented in **M11**. Structure:

```
infra/helm/
├── api/              # FastAPI backend chart
├── web/              # Next.js frontend chart
├── argocd/           # ArgoCD app-of-apps bootstrap
└── argo-rollouts/    # Canary rollout definitions (metric-based auto-rollback)
```

External charts managed via ArgoCD ApplicationSets:
- `kube-prometheus-stack` — Prometheus + Grafana + Alertmanager
- `external-secrets`      — External Secrets Operator (pulls from AWS Secrets Manager)
- `langfuse`              — Self-hosted Langfuse (LLM observability)
- `keda`                  — Kubernetes Event-Driven Autoscaling

## Usage (lint only — no cluster required)

```bash
make helm-lint
```
