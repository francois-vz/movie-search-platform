variable "name_prefix" {
  type        = string
  description = "Prefix for role names, e.g. movie-search-dev."
}

variable "project" {
  type        = string
  description = "Project name. Scopes the deploy role's IAM permissions to this project's roles."
  default     = "movie-search"
}

variable "environment" {
  type        = string
  description = "Deployment environment."
}

variable "aws_region" {
  type        = string
  description = "Region, used to build log group and DynamoDB ARNs."
}

variable "account_id" {
  type        = string
  description = "AWS account id."
}

variable "service_names" {
  type        = list(string)
  description = "Logical task names that each get their own task role."
  default     = ["api", "mcp-server", "embeddings", "pipeline", "migrate"]
}

variable "tracing_service_names" {
  type        = list(string)
  description = "Subset of service_names that emit X-Ray traces."
  default     = ["api", "mcp-server", "pipeline"]
}

variable "secret_arns" {
  type        = list(string)
  description = "Secrets the execution role may read. Nothing else is permitted."
}

variable "ecr_repository_arns" {
  type        = list(string)
  description = "Repositories the execution role may pull from and the deploy role may push to."
}

variable "github_repository" {
  type        = string
  description = "owner/repo permitted to assume the deploy role. Null disables OIDC entirely."
  default     = null
}

variable "github_subject_patterns" {
  type        = list(string)
  description = "Allowed values of the OIDC `sub` claim. Null derives them from github_repository (main branch plus the dev and prod environments)."
  default     = null
}

variable "create_github_oidc_provider" {
  type        = bool
  description = "Create the OIDC provider (account-global). False looks up an existing one."
  default     = true
}

variable "state_bucket_name" {
  type        = string
  description = "Terraform state bucket the deploy role may read and write."
}

variable "state_lock_table_name" {
  type        = string
  description = "DynamoDB lock table the deploy role may use."
  default     = "movie-search-tf-locks"
}
