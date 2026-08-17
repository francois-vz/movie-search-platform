variable "name_prefix" {
  type        = string
  description = "Prefix for resource names, e.g. movie-search-dev."
}

variable "vpc_id" {
  type        = string
  description = "VPC hosting the target group."
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnets the load balancer attaches to (at least two AZs)."
}

variable "security_group_id" {
  type        = string
  description = "Security group for the load balancer."
}

variable "certificate_arn" {
  type        = string
  description = "Existing ACM certificate ARN. Takes precedence over domain_name."
  default     = null
}

variable "domain_name" {
  type        = string
  description = "FQDN to request a certificate for and to alias at the load balancer."
  default     = null
}

variable "route53_zone_id" {
  type        = string
  description = "Hosted zone for DNS validation and the alias record."
  default     = null
}

variable "target_port" {
  type        = number
  description = "Container port the API listens on."
}

variable "health_check_path" {
  type        = string
  description = "Path the target group polls for health."
}

variable "access_logs_retention_days" {
  type        = number
  description = "Days before ALB access logs expire from S3."
}

variable "deletion_protection" {
  type        = bool
  description = "Block deletion of the load balancer."
  default     = false
}

variable "idle_timeout" {
  type        = number
  description = "Seconds an idle connection is held open. Must exceed the API request timeout."
  default     = 60
}

variable "ssl_policy" {
  type        = string
  description = "ALB security policy. The default is TLS 1.2+ with forward secrecy."
  default     = "ELBSecurityPolicy-TLS13-1-2-2021-06"
}
