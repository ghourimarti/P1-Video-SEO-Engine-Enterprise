include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/elasticache"
}

dependency "networking" {
  config_path = "../networking"
  mock_outputs = {
    redis_subnet_group_name = "mock-redis-subnet-group"
    redis_sg_id             = "sg-00000000mock"
  }
  mock_outputs_allowed_terraform_commands = ["validate", "plan"]
}

inputs = {
  redis_subnet_group_name = dependency.networking.outputs.redis_subnet_group_name
  redis_sg_id             = dependency.networking.outputs.redis_sg_id

  # dev: single node cache.t3.micro
  node_type = "cache.t3.micro"
}
