variable "project"                   { type = string }
variable "env"                      { type = string }
variable "region"                   { type = string }
variable "private_subnet_ids"       { type = list(string) }
variable "public_subnet_ids"        { type = list(string) }
variable "kubernetes_version" {
  type    = string
  default = "1.31"
}
variable "api_allowed_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
  description = "CIDRs allowed to reach EKS API server. Restrict in prod."
}
variable "system_node_instance_types" {
  type    = list(string)
  default = ["m5.large"]
}
variable "system_nodes_desired" { type = number; default = 2 }
variable "system_nodes_min"     { type = number; default = 2 }
variable "system_nodes_max"     { type = number; default = 4 }
