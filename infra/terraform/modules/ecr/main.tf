# ── ECR Repositories ──────────────────────────────────────────────────────────

locals {
  repos = {
    api = "${var.project}-api"
    web = "${var.project}-web"
  }
}

resource "aws_ecr_repository" "repos" {
  for_each             = local.repos
  name                 = each.value
  image_tag_mutability = "IMMUTABLE"   # enforce digest-pinned deploys

  image_scanning_configuration {
    scan_on_push = true   # basic AWS CVE scan on every push
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = { Name = each.value }
}

# ── Lifecycle policy — keep last 30 tagged images, purge untagged after 1 day ─
resource "aws_ecr_lifecycle_policy" "repos" {
  for_each   = aws_ecr_repository.repos
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep last 30 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = { type = "expire" }
      }
    ]
  })
}

# ── Repository policy — allow EKS nodes (via IRSA) to pull ───────────────────
data "aws_iam_policy_document" "ecr_pull" {
  statement {
    sid    = "AllowEKSPull"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = [var.eks_node_role_arn]
    }
    actions = [
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:BatchCheckLayerAvailability",
    ]
  }
}

resource "aws_ecr_repository_policy" "repos" {
  for_each   = aws_ecr_repository.repos
  repository = each.value.name
  policy     = data.aws_iam_policy_document.ecr_pull.json
}
