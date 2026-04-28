variable "project"            { type = string }
variable "env"               { type = string }
variable "region"            { type = string }
variable "vpc_cidr"          { type = string; default = "10.0.0.0/16" }
variable "single_nat_gateway" {
  type    = bool
  default = false
  description = "Use one NAT GW (dev cost saving) vs one per AZ (prod HA)"
}
