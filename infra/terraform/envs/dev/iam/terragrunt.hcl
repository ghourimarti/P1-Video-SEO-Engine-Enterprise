include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/iam"
}

dependency "eks" {
  config_path = "../eks"
  mock_outputs = {
    oidc_provider_url = "https://oidc.eks.us-east-1.amazonaws.com/id/MOCK"
    oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/MOCK"
  }
  mock_outputs_allowed_terraform_commands = ["validate", "plan"]
}

inputs = {
  oidc_provider_url = dependency.eks.outputs.oidc_provider_url
  oidc_provider_arn = dependency.eks.outputs.oidc_provider_arn
}
