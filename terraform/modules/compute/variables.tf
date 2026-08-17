variable "name_prefix" {
  type        = string
  description = "Prefix for resource names, e.g. movie-search-dev."
}

variable "environment" {
  type        = string
  description = "Deployment environment."
}

variable "aws_region" {
  type        = string
  description = "Region, used by the awslogs driver and the ADOT collector."
}

variable "cluster_name" {
  type        = string
  description = "ECS cluster name. Supplied by the root so monitoring can alarm on it without depending on this module."
}

# ---- Placement ------------------------------------------------------------

variable "vpc_id" {
  type        = string
  description = "VPC hosting the tasks and the Cloud Map namespace."
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR block."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets the tasks and EFS mount targets run in."
}

variable "ecs_security_group_id" {
  type        = string
  description = "Security group shared by all tasks."
}

variable "efs_security_group_id" {
  type        = string
  description = "Security group for the EFS mount targets."
}

variable "api_target_group_arn" {
  type        = string
  description = "Target group the API service registers into."
}

variable "service_names" {
  type        = map(string)
  description = "Map of logical name (api, mcp-server, embeddings) to ECS service name."
}

# ---- Identity and images --------------------------------------------------

variable "task_execution_role_arn" {
  type        = string
  description = "Shared ECS execution role."
}

variable "task_role_arns" {
  type        = map(string)
  description = "Map of task name to application task role ARN."
}

variable "repository_urls" {
  type        = map(string)
  description = "Map of image name to ECR repository URL."
}

variable "image_tag" {
  type        = string
  description = "Tag to deploy for the images we build."
}

variable "embeddings_image" {
  type        = string
  description = "Upstream image for the embedding model server."
}

variable "otel_collector_image" {
  type        = string
  description = "ADOT collector image for the API sidecar."
}

variable "log_group_names" {
  type        = map(string)
  description = "Map of task name to CloudWatch log group, created by modules/monitoring."
}

# ---- Secrets --------------------------------------------------------------

variable "database_url_secret_arn" {
  type        = string
  description = "Secrets Manager ARN of the postgresql:// DSN."
}

variable "jdbc_url_secret_arn" {
  type        = string
  description = "Secrets Manager ARN of the JDBC URL used by Flyway."
}

variable "db_password_secret_arn" {
  type        = string
  description = "Secrets Manager ARN of the database password used by Flyway."
}

variable "jwt_signing_key_secret_arn" {
  type        = string
  description = "Secrets Manager ARN of the JWT signing key."
}

variable "reader_secret_arn" {
  type        = string
  description = "Secrets Manager ARN of the reader client secret."
}

variable "admin_secret_arn" {
  type        = string
  description = "Secrets Manager ARN of the admin client secret."
}

# ---- Ports ----------------------------------------------------------------

variable "api_port" {
  type        = number
  description = "Port the .NET API listens on."
  default     = 8080
}

variable "mcp_port" {
  type        = number
  description = "Port the MCP server listens on."
  default     = 8000
}

variable "embeddings_port" {
  type        = number
  description = "Port the embedding server listens on. Ollama's native port."
  default     = 11434
}

# ---- Sizing ---------------------------------------------------------------

variable "api_cpu" {
  type        = number
  description = "Fargate CPU units for the API task."
}

variable "api_memory" {
  type        = number
  description = "Fargate memory (MiB) for the API task."
}

variable "api_desired_count" {
  type        = number
  description = "Initial API task count. Autoscaling owns it afterwards."
}

variable "api_min_capacity" {
  type        = number
  description = "Autoscaling floor for the API service."
}

variable "api_max_capacity" {
  type        = number
  description = "Autoscaling ceiling for the API service."
}

variable "mcp_cpu" {
  type        = number
  description = "Fargate CPU units for the MCP server task."
}

variable "mcp_memory" {
  type        = number
  description = "Fargate memory (MiB) for the MCP server task."
}

variable "mcp_desired_count" {
  type        = number
  description = "Initial MCP server task count."
}

variable "mcp_min_capacity" {
  type        = number
  description = "Autoscaling floor for the MCP server service."
}

variable "mcp_max_capacity" {
  type        = number
  description = "Autoscaling ceiling for the MCP server service."
}

variable "embeddings_cpu" {
  type        = number
  description = "Fargate CPU units for the embeddings task."
}

variable "embeddings_memory" {
  type        = number
  description = "Fargate memory (MiB) for the embeddings task."
}

variable "embeddings_desired_count" {
  type        = number
  description = "Initial embeddings task count."
}

variable "embeddings_min_capacity" {
  type        = number
  description = "Autoscaling floor for the embeddings service."
}

variable "embeddings_max_capacity" {
  type        = number
  description = "Autoscaling ceiling for the embeddings service."
}

variable "pipeline_cpu" {
  type        = number
  description = "Fargate CPU units for the one-shot pipeline task."
}

variable "pipeline_memory" {
  type        = number
  description = "Fargate memory (MiB) for the one-shot pipeline task."
}

variable "autoscaling_cpu_target" {
  type        = number
  description = "Target average CPU utilisation for target-tracking scaling."
}

variable "autoscaling_memory_target" {
  type        = number
  description = "Target average memory utilisation for target-tracking scaling."
}

# ---- Application configuration -------------------------------------------

variable "db_name" {
  type        = string
  description = "Database name."
}

variable "db_username" {
  type        = string
  description = "Database user, passed to Flyway as FLYWAY_USER."
}

variable "db_host" {
  type        = string
  description = "Database hostname."
}

variable "db_port" {
  type        = number
  description = "Database port."
}

variable "db_pool_min_size" {
  type        = number
  description = "asyncpg pool floor in the MCP server."
  default     = 2
}

variable "db_pool_max_size" {
  type        = number
  description = "asyncpg pool ceiling in the MCP server."
  default     = 10
}

variable "embedding_model" {
  type        = string
  description = "Model the embedding server pulls and serves."
}

variable "embedding_dim" {
  type        = number
  description = "Embedding dimensionality."
}

variable "embedding_batch_size" {
  type        = number
  description = "Batch size the pipeline uses when embedding."
  default     = 32
}

variable "mcp_transport" {
  type        = string
  description = "FastMCP transport. SSE locally and in this deployment."
  default     = "sse"
}

variable "log_level" {
  type        = string
  description = "Log level for the Python services."
  default     = "INFO"
}

variable "pipeline_version" {
  type        = string
  description = "Value written to the movies.pipeline_version audit column."
  default     = "0.1.0"
}

variable "jwt_issuer" {
  type        = string
  description = "JWT issuer claim."
}

variable "jwt_audience" {
  type        = string
  description = "JWT audience claim."
}

variable "jwt_expiry_minutes" {
  type        = number
  description = "Token lifetime in minutes."
  default     = 60
}

variable "reader_client_id" {
  type        = string
  description = "client_id for the reader role."
  default     = "reader"
}

variable "admin_client_id" {
  type        = string
  description = "client_id for the admin role."
  default     = "admin"
}

variable "rate_limit_per_minute" {
  type        = number
  description = "Per-principal rate limit enforced by the API."
}

variable "request_timeout_seconds" {
  type        = number
  description = "Upstream request timeout enforced by the API."
}

variable "cache_ttl_seconds" {
  type        = number
  description = "Response cache TTL."
}

variable "api_public_url" {
  type        = string
  description = "Public base URL, surfaced to the API for link generation."
}
