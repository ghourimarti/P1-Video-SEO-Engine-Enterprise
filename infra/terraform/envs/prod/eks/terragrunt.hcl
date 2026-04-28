include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/eks"
}

dependency "networking" {
  config_path = "../networking"
  mock_outputs = {
    private_subnet_ids = ["subnet-mock1", "subnet-mock2", "subnet-mock3"]
    public_subnet_ids  = ["subnet-mock4", "subnet-mock5", "subnet-mock6"]
  }
  mock_outputs_allowed_terraform_commands = ["validate", "plan"]
}

inputs = {
  private_subnet_ids = dependency.networking.outputs.private_subnet_ids
  public_subnet_ids  = dependency.networking.outputs.public_subnet_ids

  # prod: HA system node group across 3 AZs
  system_node_instance_types = ["m5.xlarge"]
  system_nodes_desired       = 2
  system_nodes_min           = 2
  system_nodes_max           = 6

  # prod: restrict API server to office + VPN CIDRs (update before apply)
  api_allowed_cidrs = ["10.0.0.0/8"]
}
