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

  # dev: single-AZ, smaller instance, no read replica
  instance_class    = "db.t3.medium"
  multi_az          = false
  create_replica    = false
  deletion_protection = false
}
