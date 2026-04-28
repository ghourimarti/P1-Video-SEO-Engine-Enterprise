include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/ecr"
}

# ECR has no dependencies on other modules
inputs = {}
