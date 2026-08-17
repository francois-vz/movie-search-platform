# ---------------------------------------------------------------------------
# dev environment root.
#
# Sized for cost: one NAT gateway, a burstable single-AZ database and small
# task counts. Everything else matches prod so that a dev plan is a meaningful
# rehearsal of a prod plan.
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

  # Partial configuration: `bucket` and `region` come from backend.hcl so that
  # the account id never lands in git. See backend.hcl.example.
  backend "s3" {
    key     = "movie-search/dev/terraform.tfstate"
    encrypt = true

    # The brief requires DynamoDB locking. Terraform >= 1.11 also offers native
    # S3 lockfiles and warns that dynamodb_table is deprecated; both are set so
    # locking keeps working either way.
    dynamodb_table = "movie-search-tf-locks"
    use_lockfile   = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "movie-search"
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}

module "platform" {
  source = "../.."

  project     = "movie-search"
  environment = "dev"
  aws_region  = var.aws_region

  # Networking — one NAT gateway across both AZs keeps dev under ~$35/month.
  vpc_cidr           = "10.10.0.0/16"
  az_count           = 2
  single_nat_gateway = true

  # Database — burstable, single AZ, short backup window, destroyable.
  db_instance_class        = "db.t4g.micro"
  db_allocated_storage     = 20
  db_max_allocated_storage = 50
  db_multi_az              = false
  db_backup_retention_days = 1
  db_deletion_protection   = false

  # TLS — supply an existing certificate, or a domain plus hosted zone to have
  # Terraform request and DNS-validate one.
  certificate_arn = var.certificate_arn
  domain_name     = var.domain_name
  route53_zone_id = var.route53_zone_id

  # Compute — minimum viable footprint, still two API tasks so a rolling
  # deployment never drops to zero.
  image_tag                = var.image_tag
  api_desired_count        = 2
  api_min_capacity         = 2
  api_max_capacity         = 4
  mcp_desired_count        = 1
  mcp_min_capacity         = 1
  mcp_max_capacity         = 2
  embeddings_desired_count = 1

  log_retention_days = 14
  alarm_email        = var.alarm_email

  github_repository           = var.github_repository
  create_github_oidc_provider = var.create_github_oidc_provider
}
