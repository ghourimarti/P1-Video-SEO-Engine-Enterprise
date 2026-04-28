# ── IAM — IRSA roles for EKS workloads ───────────────────────────────────────
#
# IRSA = IAM Roles for Service Accounts.
# Each Kubernetes service account is bound to an IAM role via an OIDC
# trust policy. Pods assume the role without static credentials.

data "aws_iam_openid_connect_provider" "eks" {
  url = var.eks_oidc_provider_url
}

locals {
  oidc_arn = data.aws_iam_openid_connect_provider.eks.arn
  oidc_sub = replace(var.eks_oidc_provider_url, "https://", "")
}

# ── Helper: OIDC trust policy ─────────────────────────────────────────────────
data "aws_iam_policy_document" "oidc_trust" {
  for_each = var.service_accounts

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_sub}:sub"
      values   = ["system:serviceaccount:${each.value.namespace}:${each.value.name}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_sub}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

# ── IRSA roles ────────────────────────────────────────────────────────────────
resource "aws_iam_role" "irsa" {
  for_each           = var.service_accounts
  name               = "${var.project}-${var.env}-${each.key}-irsa"
  assume_role_policy = data.aws_iam_policy_document.oidc_trust[each.key].json
  tags               = { ServiceAccount = each.value.name }
}

# ── Karpenter controller ──────────────────────────────────────────────────────
data "aws_iam_policy_document" "karpenter" {
  statement {
    sid    = "EC2"
    effect = "Allow"
    actions = [
      "ec2:CreateFleet", "ec2:CreateLaunchTemplate", "ec2:CreateTags",
      "ec2:DeleteLaunchTemplate", "ec2:DescribeAvailabilityZones",
      "ec2:DescribeImages", "ec2:DescribeInstances",
      "ec2:DescribeInstanceTypeOfferings", "ec2:DescribeInstanceTypes",
      "ec2:DescribeLaunchTemplates", "ec2:DescribeSecurityGroups",
      "ec2:DescribeSpotPriceHistory", "ec2:DescribeSubnets",
      "ec2:RunInstances", "ec2:TerminateInstances",
    ]
    resources = ["*"]
  }
  statement {
    sid    = "IAMPassRole"
    effect = "Allow"
    actions = ["iam:PassRole"]
    resources = [var.eks_node_role_arn]
  }
  statement {
    sid    = "SSM"
    effect = "Allow"
    actions = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:*:*:parameter/aws/service/eks/optimized-ami/*"]
  }
  statement {
    sid    = "PricingRead"
    effect = "Allow"
    actions = ["pricing:GetProducts"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "karpenter" {
  name   = "${var.project}-${var.env}-karpenter"
  policy = data.aws_iam_policy_document.karpenter.json
}

resource "aws_iam_role_policy_attachment" "karpenter" {
  role       = aws_iam_role.irsa["karpenter"].name
  policy_arn = aws_iam_policy.karpenter.arn
}

# ── External Secrets Operator ─────────────────────────────────────────────────
data "aws_iam_policy_document" "eso" {
  statement {
    sid    = "SecretsManagerRead"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      "arn:aws:secretsmanager:${var.region}:*:secret:${var.project}/${var.env}/*"
    ]
  }
}

resource "aws_iam_policy" "eso" {
  name   = "${var.project}-${var.env}-eso"
  policy = data.aws_iam_policy_document.eso.json
}

resource "aws_iam_role_policy_attachment" "eso" {
  role       = aws_iam_role.irsa["eso"].name
  policy_arn = aws_iam_policy.eso.arn
}

# ── KEDA (reads SQS / CloudWatch metrics for HPA triggers) ───────────────────
data "aws_iam_policy_document" "keda" {
  statement {
    sid    = "CloudWatchMetrics"
    effect = "Allow"
    actions = [
      "cloudwatch:GetMetricData",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:ListMetrics",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "keda" {
  name   = "${var.project}-${var.env}-keda"
  policy = data.aws_iam_policy_document.keda.json
}

resource "aws_iam_role_policy_attachment" "keda" {
  role       = aws_iam_role.irsa["keda"].name
  policy_arn = aws_iam_policy.keda.arn
}

# ── API pod IRSA (Secrets Manager read for runtime secrets) ───────────────────
data "aws_iam_policy_document" "api_pod" {
  statement {
    sid    = "SecretsRead"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      "arn:aws:secretsmanager:${var.region}:*:secret:${var.project}/${var.env}/api/*"
    ]
  }
}

resource "aws_iam_policy" "api_pod" {
  name   = "${var.project}-${var.env}-api-pod"
  policy = data.aws_iam_policy_document.api_pod.json
}

resource "aws_iam_role_policy_attachment" "api_pod" {
  role       = aws_iam_role.irsa["api"].name
  policy_arn = aws_iam_policy.api_pod.arn
}
