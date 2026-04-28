include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/networking"
}

inputs = {
  az_count           = 2
  single_nat_gateway = true   # cost optimisation for dev
}
