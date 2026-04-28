include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/eks"
}

dependency "networking" {
  config_path = "../networking"
  mock_outputs = {
    private_subnet_ids = ["subnet-mock1", "subnet-mock2"]
    public_subnet_ids  = ["subnet-mock3", "subnet-mock4"]
  }
  mock_outputs_allowed_terraform_commands = ["validate", "plan"]
}

inputs = {
  private_subnet_ids = dependency.networking.outputs.private_subnet_ids
  public_subnet_ids  = dependency.networking.outputs.public_subnet_ids

  # dev: smaller nodes, single-node system group
  system_node_instance_types = ["m5.large"]
  system_nodes_desired       = 1
  system_nodes_min           = 1
  system_nodes_max           = 2

  # dev: allow all CIDRs for easy debugging (lock down in prod)
  api_allowed_cidrs = ["0.0.0.0/0"]
}
