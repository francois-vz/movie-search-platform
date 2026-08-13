# Root Terraform composition (Part 6.2).
# Orchestrator: AWS ECS Fargate (justification in terraform/README.md).
#
# TODO: wire modules (networking, ecr, rds, secrets, iam, compute, alb, monitoring).

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state — S3 backend + DynamoDB locking.
  # backend "s3" {
  #   bucket         = "TODO-tfstate-bucket"
  #   key            = "movie-search/terraform.tfstate"
  #   region         = "TODO"
  #   dynamodb_table = "TODO-tf-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "movie-search"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
