# Root Terragrunt configuration
# All child terragrunt.hcl files include this via find_in_parent_folders().

locals {
  # Parse the env name from the directory path: envs/dev → "dev"
  env_vars = read_terragrunt_config(find_in_parent_folders("env.hcl"))
  env      = local.env_vars.locals.env
  project  = "anime-rag"
  region   = "us-east-1"
  account  = get_aws_account_id()
}

# ── Remote state (S3 + DynamoDB lock) ────────────────────────────────────────
remote_state {
  backend = "s3"
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite_terragrunt"
  }
  config = {
    bucket         = "${local.project}-tfstate-${local.account}-${local.region}"
    key            = "${local.env}/${path_relative_to_include()}/terraform.tfstate"
    region         = local.region
    encrypt        = true
    dynamodb_table = "${local.project}-tflock"
  }
}

# ── Common provider block ─────────────────────────────────────────────────────
generate "provider" {
  path      = "provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<-EOF
    terraform {
      required_version = ">= 1.8"
      required_providers {
        aws = {
          source  = "hashicorp/aws"
          version = "~> 5.50"
        }
        kubernetes = {
          source  = "hashicorp/kubernetes"
          version = "~> 2.30"
        }
        helm = {
          source  = "hashicorp/helm"
          version = "~> 2.13"
        }
      }
    }

    provider "aws" {
      region = "${local.region}"
      default_tags {
        tags = {
          Project     = "${local.project}"
          Environment = "${local.env}"
          ManagedBy   = "terraform"
        }
      }
    }
  EOF
}

# ── Common inputs available to all child modules ──────────────────────────────
inputs = {
  project = local.project
  env     = local.env
  region  = local.region
}
