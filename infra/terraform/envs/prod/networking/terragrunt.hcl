include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/networking"
}

inputs = {
  az_count           = 3
  single_nat_gateway = false   # one NAT GW per AZ for HA
}
