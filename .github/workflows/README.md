# GitHub Actions Workflows

Implemented in **M12**. Pipeline overview:

| Workflow | Trigger | Jobs |
|---|---|---|
| `ci.yaml` | push / PR to main | lint → unit tests → integration tests → RAGAS gate → docker build |
| `cd.yaml` | push to main (after CI green) | push to ECR → ArgoCD sync (dev) → smoke test → promote to prod |
| `eval-nightly.yaml` | cron `0 2 * * *` | full RAGAS eval on 100 golden samples → post to Slack |
| `model-drift.yaml` | cron `0 8 * * 1` | embedding drift check → alert if cosine shift > threshold |

All workflows use OIDC (no long-lived AWS credentials stored as secrets).
