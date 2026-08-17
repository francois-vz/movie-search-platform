variable "name_prefix" {
  type        = string
  description = "Prefix for resource names, e.g. movie-search-dev."
}

variable "environment" {
  type        = string
  description = "Deployment environment. Controls apply_immediately and secret recovery windows."
}

variable "vpc_id" {
  type        = string
  description = "VPC hosting the database."
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet ids for the DB subnet group."
}

variable "security_group_id" {
  type        = string
  description = "Security group allowing 5432 from the Fargate tasks only."
}

variable "engine_version" {
  type        = string
  description = "PostgreSQL major version. The brief requires 16."
  default     = "16"
}

variable "db_name" {
  type        = string
  description = "Initial database name."
}

variable "db_username" {
  type        = string
  description = "Master username."
}

variable "instance_class" {
  type        = string
  description = "RDS instance class."
}

variable "allocated_storage" {
  type        = number
  description = "Initial storage in GiB."
}

variable "max_allocated_storage" {
  type        = number
  description = "Storage autoscaling ceiling in GiB."
}

variable "multi_az" {
  type        = bool
  description = "Deploy a standby in a second AZ."
}

variable "backup_retention_days" {
  type        = number
  description = "Automated backup retention in days."
}

variable "deletion_protection" {
  type        = bool
  description = "Block deletion. Also drives whether a final snapshot is taken."
}

variable "performance_insights" {
  type        = bool
  description = "Enable Performance Insights."
  default     = false
}

variable "monitoring_interval" {
  type        = number
  description = "Enhanced monitoring granularity in seconds. 0 disables it."
  default     = 0
}

variable "log_group_retention_days" {
  type        = number
  description = "Retention for the exported PostgreSQL log group."
  default     = 30
}
