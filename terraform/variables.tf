variable "aws_region" {
  type        = string
  description = "AWS region to deploy into."
}

variable "environment" {
  type        = string
  description = "Deployment environment (dev, prod)."
}

# TODO: vpc_cidr, db instance sizing, container image tags, desired counts, etc.
