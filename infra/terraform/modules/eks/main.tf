# ── EKS 1.31 cluster + managed node group + Karpenter ─────────────────────────

locals {
  cluster_name = "${var.project}-${var.env}"
}

# ── EKS Cluster ───────────────────────────────────────────────────────────────
resource "aws_eks_cluster" "main" {
  name    = local.cluster_name
  version = var.kubernetes_version

  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids              = concat(var.private_subnet_ids, var.public_subnet_ids)
    endpoint_private_access = true
    endpoint_public_access  = true   # flip to false once VPN/bastion is set up
    public_access_cidrs     = var.api_allowed_cidrs
  }

  # Enable control-plane logging
  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  # Secret encryption at rest
  encryption_config {
    resources = ["secrets"]
    provider {
      key_arn = aws_kms_key.eks.arn
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.cluster_policy,
    aws_iam_role_policy_attachment.cluster_vpc_policy,
    aws_cloudwatch_log_group.eks_control_plane,
  ]

  tags = { Name = local.cluster_name }
}

# ── OIDC provider (required for IRSA) ────────────────────────────────────────
data "tls_certificate" "eks" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

# ── KMS key for secret encryption ─────────────────────────────────────────────
resource "aws_kms_key" "eks" {
  description             = "EKS secret encryption — ${local.cluster_name}"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "eks" {
  name          = "alias/${local.cluster_name}-eks"
  target_key_id = aws_kms_key.eks.key_id
}

# ── CloudWatch log group ──────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "eks_control_plane" {
  name              = "/aws/eks/${local.cluster_name}/cluster"
  retention_in_days = 30
}

# ── Cluster IAM role ──────────────────────────────────────────────────────────
data "aws_iam_policy_document" "cluster_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${local.cluster_name}-cluster-role"
  assume_role_policy = data.aws_iam_policy_document.cluster_assume.json
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role_policy_attachment" "cluster_vpc_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSVPCResourceController"
}

# ── Node group IAM role ───────────────────────────────────────────────────────
data "aws_iam_policy_document" "node_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${local.cluster_name}-node-role"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json
}

locals {
  node_policies = [
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
  ]
}

resource "aws_iam_role_policy_attachment" "node" {
  count      = length(local.node_policies)
  role       = aws_iam_role.node.name
  policy_arn = local.node_policies[count.index]
}

# ── EKS Managed Node Group (system / spot instances for baseline capacity) ────
resource "aws_eks_node_group" "system" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${local.cluster_name}-system"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids

  # Use On-Demand for system workloads (CoreDNS, Karpenter, ESO, etc.)
  capacity_type  = "ON_DEMAND"
  instance_types = var.system_node_instance_types

  scaling_config {
    desired_size = var.system_nodes_desired
    min_size     = var.system_nodes_min
    max_size     = var.system_nodes_max
  }

  update_config {
    max_unavailable = 1
  }

  labels = {
    "node.kubernetes.io/purpose" = "system"
  }

  taint {
    key    = "CriticalAddonsOnly"
    value  = "true"
    effect = "NO_SCHEDULE"
  }

  depends_on = [aws_iam_role_policy_attachment.node]

  tags = { Name = "${local.cluster_name}-system-node" }

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]   # Karpenter manages desired
  }
}

# ── EKS Add-ons ──────────────────────────────────────────────────────────────
resource "aws_eks_addon" "vpc_cni" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "vpc-cni"
  resolve_conflicts_on_update = "OVERWRITE"
}

resource "aws_eks_addon" "coredns" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "coredns"
  resolve_conflicts_on_update = "OVERWRITE"
  depends_on               = [aws_eks_node_group.system]
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "kube-proxy"
  resolve_conflicts_on_update = "OVERWRITE"
}

resource "aws_eks_addon" "ebs_csi" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "aws-ebs-csi-driver"
  resolve_conflicts_on_update = "OVERWRITE"
}

# ── Karpenter NodePool + EC2NodeClass (via Kubernetes resources) ──────────────
# Note: Karpenter itself is installed via Helm (M11).
# These Kubernetes resources configure what Karpenter is allowed to provision.

resource "kubernetes_manifest" "karpenter_node_class" {
  manifest = {
    apiVersion = "karpenter.k8s.aws/v1beta1"
    kind       = "EC2NodeClass"
    metadata   = { name = "default" }
    spec = {
      amiFamily = "AL2"
      role       = aws_iam_role.node.name
      subnetSelectorTerms = [
        { tags = { "karpenter.sh/discovery" = local.cluster_name } }
      ]
      securityGroupSelectorTerms = [
        { tags = { "karpenter.sh/discovery" = local.cluster_name } }
      ]
    }
  }

  depends_on = [aws_eks_cluster.main]
}

resource "kubernetes_manifest" "karpenter_node_pool" {
  manifest = {
    apiVersion = "karpenter.sh/v1beta1"
    kind       = "NodePool"
    metadata   = { name = "default" }
    spec = {
      template = {
        spec = {
          nodeClassRef = { name = "default" }
          requirements = [
            { key = "karpenter.sh/capacity-type",      operator = "In", values = ["spot", "on-demand"] },
            { key = "kubernetes.io/arch",               operator = "In", values = ["amd64"] },
            { key = "node.kubernetes.io/instance-type", operator = "In",
              values = ["m5.large", "m5.xlarge", "m5.2xlarge", "c5.large", "c5.xlarge"] },
          ]
        }
      }
      limits   = { cpu = "100" }
      disruption = {
        consolidationPolicy = "WhenUnderutilized"
        consolidateAfter    = "30s"
      }
    }
  }

  depends_on = [aws_eks_cluster.main]
}
