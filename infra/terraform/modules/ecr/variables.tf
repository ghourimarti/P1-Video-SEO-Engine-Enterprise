variable "project"           { type = string }
variable "env"              { type = string }
variable "region"           { type = string }
variable "eks_node_role_arn" {
  type        = string
  description = "IAM role ARN of EKS managed node group — granted ECR pull permissions"
}
