# ---------------------------------------------------------------------------
# prod environment root.
#
# Same composition module as dev, sized for resilience: a NAT gateway per AZ,
# Multi-AZ RDS with deletion protection and Performance Insights, longer
# retention and higher autoscaling ceilings.
#
#   terraform init -backend-config=backend.hcl
#   terraform plan
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    key     = "movie-search/prod/terraform.tfstate"
    encrypt = true

    dynamodb_table = "movie-search-tf-locks"
    use_lockfile   = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "movie-search"
      Environment = "prod"
      ManagedBy   = "terraform"
    }
  }
}

module "platform" {
  source = "../.."

  project     = "movie-search"
  environment = "prod"
  aws_region  = var.aws_region

  # Networking — a NAT gateway per AZ so a zone failure cannot cut egress.
  vpc_cidr           = "10.20.0.0/16"
  az_count           = 2
  single_nat_gateway = false

  # Database — Multi-AZ, protected, four weeks of backups.
  db_instance_class        = "db.t4g.medium"
  db_allocated_storage     = 50
  db_max_allocated_storage = 500
  db_multi_az              = true
  db_backup_retention_days = 30
  db_deletion_protection   = true

  certificate_arn = var.certificate_arn
  domain_name     = var.domain_name
  route53_zone_id = var.route53_zone_id

  image_tag                = var.image_tag
  api_cpu                  = 1024
  api_memory               = 2048
  api_desired_count        = 3
  api_min_capacity         = 3
  api_max_capacity         = 12
  mcp_cpu                  = 1024
  mcp_memory               = 2048
  mcp_desired_count        = 2
  mcp_min_capacity         = 2
  mcp_max_capacity         = 8
  embeddings_desired_count = 2
  embeddings_max_capacity  = 4

  log_retention_days = 90
  alarm_email        = var.alarm_email

  github_repository = var.github_repository

  # The OIDC provider is account-global and is created by the dev root.
  create_github_oidc_provider = false
}
