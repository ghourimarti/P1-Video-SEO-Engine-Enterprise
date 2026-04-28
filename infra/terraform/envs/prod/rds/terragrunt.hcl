include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/rds"
}

dependency "networking" {
  config_path = "../networking"
  mock_outputs = {
    db_subnet_group_name = "mock-db-subnet-group"
    rds_sg_id            = "sg-00000000mock"
  }
  mock_outputs_allowed_terraform_commands = ["validate", "plan"]
}

inputs = {
  db_subnet_group_name = dependency.networking.outputs.db_subnet_group_name
  rds_sg_id            = dependency.networking.outputs.rds_sg_id

  # prod: Multi-AZ, larger instance, read replica, deletion protection on
  instance_class      = "db.r6g.large"
  multi_az            = true
  create_replica      = true
  deletion_protection = true
}
