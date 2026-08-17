# ---------------------------------------------------------------------------
# Movie Search Platform — composition module (Part 6.2).
#
# This directory is a *module*, not a root: it declares no provider and no
# backend. The roots are terraform/environments/{dev,prod}, which own the S3
# backend, the provider (including default_tags) and the per-environment sizing.
#
# Orchestrator: AWS ECS Fargate. Justification in terraform/README.md.
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project}-${var.environment}"

  # ECS names are derived here rather than read back from module.compute so
  # that the monitoring module (which alarms on them) does not depend on
  # compute, and compute can depend on monitoring for its log groups.
  cluster_name = local.name_prefix

  service_names = {
    api        = "${local.name_prefix}-api"
    mcp-server = "${local.name_prefix}-mcp-server"
    embeddings = "${local.name_prefix}-embeddings"
  }

  # Images we build and push to ECR. `embeddings` runs an upstream image.
  ecr_repositories = ["api", "mcp-server", "pipeline", "migrate"]

  # One log group per task, including the two run-to-completion tasks.
  log_group_services = ["api", "mcp-server", "embeddings", "pipeline", "migrate"]

  # Matches the names created by terraform/bootstrap.
  state_bucket_name     = "${var.project}-tfstate-${data.aws_caller_identity.current.account_id}"
  state_lock_table_name = "${var.project}-tf-locks"
}

# ---- Networking -----------------------------------------------------------

module "networking" {
  source = "./modules/networking"

  name_prefix              = local.name_prefix
  aws_region               = var.aws_region
  vpc_cidr                 = var.vpc_cidr
  az_count                 = var.az_count
  single_nat_gateway       = var.single_nat_gateway
  flow_logs_retention_days = var.flow_logs_retention_days
  api_port                 = 8080
  mcp_port                 = 8000
  embeddings_port          = 11434
}

# ---- Container registries -------------------------------------------------

module "ecr" {
  source = "./modules/ecr"

  name_prefix           = local.name_prefix
  repository_names      = local.ecr_repositories
  image_retention_count = var.ecr_image_retention_count
}

# ---- Application secrets --------------------------------------------------
# The database credential lives with the database (see modules/rds); this
# module owns the application-level secrets.

module "secrets" {
  source = "./modules/secrets"

  name_prefix = local.name_prefix
  environment = var.environment
}

# ---- Database -------------------------------------------------------------

module "rds" {
  source = "./modules/rds"

  name_prefix              = local.name_prefix
  environment              = var.environment
  vpc_id                   = module.networking.vpc_id
  subnet_ids               = module.networking.private_subnet_ids
  security_group_id        = module.networking.rds_security_group_id
  db_name                  = var.db_name
  db_username              = var.db_username
  instance_class           = var.db_instance_class
  allocated_storage        = var.db_allocated_storage
  max_allocated_storage    = var.db_max_allocated_storage
  multi_az                 = var.db_multi_az
  backup_retention_days    = var.db_backup_retention_days
  deletion_protection      = var.db_deletion_protection
  monitoring_interval      = var.environment == "prod" ? 60 : 0
  performance_insights     = var.environment == "prod"
  log_group_retention_days = var.log_retention_days
}

# ---- IAM ------------------------------------------------------------------

module "iam" {
  source = "./modules/iam"

  name_prefix = local.name_prefix
  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region
  account_id  = data.aws_caller_identity.current.account_id

  state_bucket_name     = local.state_bucket_name
  state_lock_table_name = local.state_lock_table_name

  # Least privilege: the execution role may read exactly these secrets.
  secret_arns = concat(
    module.secrets.secret_arns,
    module.rds.secret_arns,
  )
  ecr_repository_arns = module.ecr.repository_arns

  github_repository           = var.github_repository
  create_github_oidc_provider = var.create_github_oidc_provider
}

# ---- Load balancer --------------------------------------------------------

module "alb" {
  source = "./modules/alb"

  name_prefix                = local.name_prefix
  vpc_id                     = module.networking.vpc_id
  public_subnet_ids          = module.networking.public_subnet_ids
  security_group_id          = module.networking.alb_security_group_id
  certificate_arn            = var.certificate_arn
  domain_name                = var.domain_name
  route53_zone_id            = var.route53_zone_id
  access_logs_retention_days = var.alb_access_logs_retention_days
  target_port                = 8080
  health_check_path          = "/health"
  deletion_protection        = var.environment == "prod"
}

# ---- Observability --------------------------------------------------------
# Owns the log groups so that compute can reference them, and alarms on the
# deterministic cluster/service names from locals.

module "monitoring" {
  source = "./modules/monitoring"

  name_prefix        = local.name_prefix
  aws_region         = var.aws_region
  log_group_services = local.log_group_services
  log_retention_days = var.log_retention_days

  cluster_name            = local.cluster_name
  service_names           = values(local.service_names)
  alb_arn_suffix          = module.alb.alb_arn_suffix
  target_group_arn_suffix = module.alb.target_group_arn_suffix
  db_instance_identifier  = module.rds.instance_identifier
  alarm_email             = var.alarm_email
  p95_latency_threshold   = var.api_p95_latency_threshold_seconds
  xray_sampling_rate      = var.xray_sampling_rate
  autoscaling_cpu_target  = var.autoscaling_cpu_target
}

# ---- Compute (ECS Fargate) ------------------------------------------------

module "compute" {
  source = "./modules/compute"

  name_prefix  = local.name_prefix
  environment  = var.environment
  aws_region   = var.aws_region
  cluster_name = local.cluster_name

  vpc_id                = module.networking.vpc_id
  vpc_cidr              = module.networking.vpc_cidr
  private_subnet_ids    = module.networking.private_subnet_ids
  ecs_security_group_id = module.networking.ecs_security_group_id
  efs_security_group_id = module.networking.efs_security_group_id
  api_target_group_arn  = module.alb.target_group_arn
  service_names         = local.service_names
  log_group_names       = module.monitoring.log_group_names

  task_execution_role_arn = module.iam.task_execution_role_arn
  task_role_arns          = module.iam.task_role_arns
  repository_urls         = module.ecr.repository_urls
  image_tag               = var.image_tag
  embeddings_image        = var.embeddings_image
  otel_collector_image    = var.otel_collector_image

  database_url_secret_arn    = module.rds.database_url_secret_arn
  jdbc_url_secret_arn        = module.rds.jdbc_url_secret_arn
  db_password_secret_arn     = module.rds.password_secret_arn
  jwt_signing_key_secret_arn = module.secrets.jwt_signing_key_secret_arn
  reader_secret_arn          = module.secrets.reader_client_secret_arn
  admin_secret_arn           = module.secrets.admin_client_secret_arn

  api_cpu                  = var.api_cpu
  api_memory               = var.api_memory
  api_desired_count        = var.api_desired_count
  api_min_capacity         = var.api_min_capacity
  api_max_capacity         = var.api_max_capacity
  mcp_cpu                  = var.mcp_cpu
  mcp_memory               = var.mcp_memory
  mcp_desired_count        = var.mcp_desired_count
  mcp_min_capacity         = var.mcp_min_capacity
  mcp_max_capacity         = var.mcp_max_capacity
  embeddings_cpu           = var.embeddings_cpu
  embeddings_memory        = var.embeddings_memory
  embeddings_desired_count = var.embeddings_desired_count
  embeddings_min_capacity  = var.embeddings_min_capacity
  embeddings_max_capacity  = var.embeddings_max_capacity
  pipeline_cpu             = var.pipeline_cpu
  pipeline_memory          = var.pipeline_memory

  autoscaling_cpu_target    = var.autoscaling_cpu_target
  autoscaling_memory_target = var.autoscaling_memory_target

  db_name                 = var.db_name
  db_username             = var.db_username
  db_host                 = module.rds.address
  db_port                 = module.rds.port
  embedding_model         = var.embedding_model
  embedding_dim           = var.embedding_dim
  jwt_issuer              = var.jwt_issuer
  jwt_audience            = var.jwt_audience
  rate_limit_per_minute   = var.rate_limit_per_minute
  request_timeout_seconds = var.request_timeout_seconds
  cache_ttl_seconds       = var.cache_ttl_seconds
  api_public_url          = module.alb.api_base_url

  # Targets must not be registered before the listener exists. The target group
  # ARN alone does not express that ordering, so depend on the whole module.
  depends_on = [module.alb]
}
