# Terraform IaC

Implemented in **M10**. Structure:

```
infra/terraform/
├── modules/
│   ├── network/      # VPC, subnets, NAT GW, security groups
│   ├── eks/          # EKS 1.31 cluster + Karpenter node autoscaling
│   ├── data/         # RDS Postgres 16 (pgvector), ElastiCache Redis 7
│   ├── ecr/          # ECR repos (api, web)
│   ├── storage/      # S3 buckets, EFS for Langfuse
│   └── iam/          # IRSA roles for ESO, Karpenter, KEDA
├── envs/
│   ├── dev/          # terragrunt.hcl + env-specific overrides
│   └── prod/         # terragrunt.hcl + env-specific overrides
└── terragrunt.hcl    # root config (remote state in S3 + DynamoDB lock)
```

## Usage (IaC only — no real AWS spend in dev)

```bash
make tf-plan           # runs: terragrunt run-all plan --terragrunt-working-dir envs/dev
```
