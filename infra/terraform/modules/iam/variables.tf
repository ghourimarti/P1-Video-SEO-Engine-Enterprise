variable "project"               { type = string }
variable "env"                  { type = string }
variable "region"               { type = string }
variable "eks_oidc_provider_url" { type = string }
variable "eks_node_role_arn"    { type = string }

variable "service_accounts" {
  description = "Map of IRSA service accounts to create"
  type = map(object({
    namespace = string
    name      = string
  }))
  default = {
    karpenter = { namespace = "kube-system",  name = "karpenter" }
    eso       = { namespace = "external-secrets", name = "external-secrets" }
    keda      = { namespace = "keda",         name = "keda-operator" }
    api       = { namespace = "anime-rag",    name = "api" }
  }
}
