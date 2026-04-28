variable "project"              { type = string }
variable "env"                 { type = string }
variable "region"              { type = string }
variable "db_subnet_group_name" { type = string }
variable "rds_sg_id"           { type = string }
variable "db_name"             { type = string; default = "anime_rag" }
variable "db_username"         { type = string; default = "anime_rag" }
variable "instance_class" {
  type    = string
  default = "db.t3.medium"
}
variable "allocated_storage_gb" {
  type    = number
  default = 50
}
variable "max_connections" {
  type    = string
  default = "200"
}
