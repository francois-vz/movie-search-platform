variable "aws_region" {
  type        = string
  description = "AWS region for the prod environment."
  default     = "eu-west-1"
}

variable "image_tag" {
  type        = string
  description = "Image tag to deploy. CD passes the git SHA."
  default     = "latest"
}

variable "certificate_arn" {
  type        = string
  description = "Existing ACM certificate ARN for HTTPS. Leave null to request one for domain_name."
  default     = null
}

variable "domain_name" {
  type        = string
  description = "FQDN for the prod API, e.g. api.example.com. Required when certificate_arn is null."
  default     = null
}

variable "route53_zone_id" {
  type        = string
  description = "Hosted zone id used for ACM validation and the alias record."
  default     = null
}

variable "alarm_email" {
  type        = string
  description = "Optional address subscribed to CloudWatch alarms."
  default     = null
}

variable "github_repository" {
  type        = string
  description = "owner/repo permitted to assume the CD role via OIDC."
  default     = null
}

# The provider itself is created by the dev root (it is account-global), so
# there is no create_github_oidc_provider variable here.
