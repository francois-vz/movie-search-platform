# ---------------------------------------------------------------------------
# Composition module inputs. Environment roots (environments/dev, prod) supply
# these; defaults here describe the smallest sensible deployment.
# ---------------------------------------------------------------------------

variable "project" {
  type        = string
  description = "Project name, used as the prefix for every resource name and the Project tag."
  default     = "movie-search"
}

variable "environment" {
  type        = string
  description = "Deployment environment (dev, prod)."

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be one of: dev, prod."
  }
}

variable "aws_region" {
  type        = string
  description = "AWS region to deploy into."
}

# ---- Networking -----------------------------------------------------------

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC."
  default     = "10.0.0.0/16"
}

variable "az_count" {
  type        = number
  description = "Number of availability zones to spread subnets across."
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be 2 or 3 (the ALB requires at least two)."
  }
}

variable "single_nat_gateway" {
  type        = bool
  description = "Use one shared NAT gateway (cheap, dev) instead of one per AZ (resilient, prod)."
  default     = true
}

variable "flow_logs_retention_days" {
  type        = number
  description = "Retention in days for the VPC Flow Logs log group."
  default     = 30
}

# ---- Database -------------------------------------------------------------

variable "db_name" {
  type        = string
  description = "Initial database name."
  default     = "movies"
}

variable "db_username" {
  type        = string
  description = "RDS master username. The password is generated and stored in Secrets Manager."
  default     = "movies"
}

variable "db_instance_class" {
  type        = string
  description = "RDS instance class."
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  type        = number
  description = "Initial storage (GiB) for RDS."
  default     = 20
}

variable "db_max_allocated_storage" {
  type        = number
  description = "Upper bound (GiB) for RDS storage autoscaling."
  default     = 100
}

variable "db_multi_az" {
  type        = bool
  description = "Run RDS across two AZs. Recommended for prod."
  default     = false
}

variable "db_backup_retention_days" {
  type        = number
  description = "Automated backup retention in days."
  default     = 7
}

variable "db_deletion_protection" {
  type        = bool
  description = "Block accidental `terraform destroy` of the database."
  default     = false
}

# ---- Load balancer / TLS --------------------------------------------------

variable "certificate_arn" {
  type        = string
  description = "ARN of an existing ACM certificate for the HTTPS listener. Leave null to have Terraform request one for domain_name."
  default     = null
}

variable "domain_name" {
  type        = string
  description = "Fully-qualified domain name for the API. Required when certificate_arn is null."
  default     = null
}

variable "route53_zone_id" {
  type        = string
  description = "Route53 hosted zone used for ACM DNS validation and the API alias record. Required when certificate_arn is null."
  default     = null
}

variable "alb_access_logs_retention_days" {
  type        = number
  description = "Lifecycle expiry in days for ALB access logs in S3."
  default     = 90
}

# ---- Container images -----------------------------------------------------

variable "image_tag" {
  type        = string
  description = "Tag applied to the api / mcp-server / pipeline / migrate images in ECR. CD sets this to the git SHA."
  default     = "latest"
}

variable "embeddings_image" {
  type        = string
  description = "Fully-qualified image for the embedding model server. Pulled from Docker Hub via NAT."
  default     = "ollama/ollama:0.6.8"
}

variable "embedding_model" {
  type        = string
  description = "Model the embeddings container pulls and serves."
  default     = "nomic-embed-text"
}

variable "embedding_dim" {
  type        = number
  description = "Embedding dimensionality. Must match the vector(N) column in the Flyway schema."
  default     = 768
}

variable "otel_collector_image" {
  type        = string
  description = "ADOT collector sidecar image. Hosted on ECR Public, so it is not subject to Docker Hub pull limits."
  default     = "public.ecr.aws/aws-observability/aws-otel-collector:v0.41.1"
}

variable "ecr_image_retention_count" {
  type        = number
  description = "Number of tagged images to retain per ECR repository."
  default     = 20
}

# ---- Service sizing -------------------------------------------------------

variable "api_cpu" {
  type        = number
  description = "Fargate CPU units for the .NET API task."
  default     = 512
}

variable "api_memory" {
  type        = number
  description = "Fargate memory (MiB) for the .NET API task."
  default     = 1024
}

variable "api_desired_count" {
  type        = number
  description = "Baseline task count for the API service."
  default     = 2
}

variable "api_min_capacity" {
  type        = number
  description = "Autoscaling floor for the API service."
  default     = 2
}

variable "api_max_capacity" {
  type        = number
  description = "Autoscaling ceiling for the API service."
  default     = 6
}

variable "mcp_cpu" {
  type        = number
  description = "Fargate CPU units for the MCP server task."
  default     = 512
}

variable "mcp_memory" {
  type        = number
  description = "Fargate memory (MiB) for the MCP server task."
  default     = 1024
}

variable "mcp_desired_count" {
  type        = number
  description = "Baseline task count for the MCP server service."
  default     = 1
}

variable "mcp_min_capacity" {
  type        = number
  description = "Autoscaling floor for the MCP server service."
  default     = 1
}

variable "mcp_max_capacity" {
  type        = number
  description = "Autoscaling ceiling for the MCP server service."
  default     = 4
}

# Ollama holds the model in memory; it needs materially more headroom than the
# stateless services. Scaling it out also means re-pulling per task, so the
# ceiling stays low and the model cache lives on EFS.
variable "embeddings_cpu" {
  type        = number
  description = "Fargate CPU units for the embedding model server."
  default     = 2048
}

variable "embeddings_memory" {
  type        = number
  description = "Fargate memory (MiB) for the embedding model server."
  default     = 4096
}

variable "embeddings_desired_count" {
  type        = number
  description = "Baseline task count for the embeddings service."
  default     = 1
}

variable "embeddings_min_capacity" {
  type        = number
  description = "Autoscaling floor for the embeddings service."
  default     = 1
}

variable "embeddings_max_capacity" {
  type        = number
  description = "Autoscaling ceiling for the embeddings service."
  default     = 2
}

variable "pipeline_cpu" {
  type        = number
  description = "Fargate CPU units for the one-shot pipeline task."
  default     = 1024
}

variable "pipeline_memory" {
  type        = number
  description = "Fargate memory (MiB) for the one-shot pipeline task."
  default     = 2048
}

variable "autoscaling_cpu_target" {
  type        = number
  description = "Target average CPU utilisation (percent) for target-tracking autoscaling."
  default     = 60
}

variable "autoscaling_memory_target" {
  type        = number
  description = "Target average memory utilisation (percent) for target-tracking autoscaling."
  default     = 70
}

# ---- Application configuration -------------------------------------------

variable "jwt_issuer" {
  type        = string
  description = "JWT issuer claim served by the API."
  default     = "movie-search"
}

variable "jwt_audience" {
  type        = string
  description = "JWT audience claim served by the API."
  default     = "movie-search-clients"
}

variable "rate_limit_per_minute" {
  type        = number
  description = "Per-principal request rate limit enforced by the API."
  default     = 60
}

variable "request_timeout_seconds" {
  type        = number
  description = "Upstream request timeout enforced by the API."
  default     = 30
}

variable "cache_ttl_seconds" {
  type        = number
  description = "Response cache TTL for repeated identical searches."
  default     = 60
}

# ---- Observability --------------------------------------------------------

variable "log_retention_days" {
  type        = number
  description = "Retention in days for the ECS task log groups."
  default     = 30
}

variable "alarm_email" {
  type        = string
  description = "Optional address subscribed to the CloudWatch alarm SNS topic."
  default     = null
}

variable "api_p95_latency_threshold_seconds" {
  type        = number
  description = "Alarm threshold for ALB target p95 latency. The brief requires p95 < 500ms."
  default     = 0.5
}

variable "xray_sampling_rate" {
  type        = number
  description = "Fraction of requests sampled for X-Ray beyond the reservoir."
  default     = 0.1
}

# ---- CI/CD ----------------------------------------------------------------

variable "github_repository" {
  type        = string
  description = "owner/repo allowed to assume the CD deployment role via OIDC. Null disables the OIDC role."
  default     = null
}

variable "create_github_oidc_provider" {
  type        = bool
  description = "Create the GitHub OIDC provider. Set false if the account already has one (it is account-global)."
  default     = true
}
