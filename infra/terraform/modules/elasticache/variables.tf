variable "project"                { type = string }
variable "env"                   { type = string }
variable "region"                { type = string }
variable "redis_subnet_group_name" { type = string }
variable "redis_sg_id"           { type = string }
variable "node_type" {
  type    = string
  default = "cache.t3.medium"
}
