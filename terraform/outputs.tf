output "api_url" {
  description = "Public HTTPS base URL of the .NET API."
  value       = module.alb.api_base_url
}

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer."
  value       = module.alb.alb_dns_name
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port). Reachable only from inside the VPC."
  value       = module.rds.endpoint
  sensitive   = true
}

output "database_url_secret_arn" {
  description = "Secrets Manager ARN holding the full DATABASE_URL DSN."
  value       = module.rds.database_url_secret_arn
}

output "ecr_repository_urls" {
  description = "Map of image name to ECR repository URL, consumed by the CD workflow."
  value       = module.ecr.repository_urls
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = module.compute.cluster_name
}

output "ecs_service_names" {
  description = "Map of logical service name to ECS service name."
  value       = module.compute.service_names
}

output "pipeline_task_definition_arn" {
  description = "Task definition for the one-shot data pipeline. Invoke with `aws ecs run-task`."
  value       = module.compute.pipeline_task_definition_arn
}

output "migrate_task_definition_arn" {
  description = "Task definition for the Flyway migration job. Invoke with `aws ecs run-task`."
  value       = module.compute.migrate_task_definition_arn
}

output "run_task_network_configuration" {
  description = "awsvpc network configuration to pass to `aws ecs run-task` for the pipeline and migrate tasks."
  value = {
    subnets         = module.networking.private_subnet_ids
    security_groups = [module.networking.ecs_security_group_id]
  }
}

output "github_deploy_role_arn" {
  description = "IAM role the GitHub Actions CD workflow assumes via OIDC."
  value       = module.iam.github_deploy_role_arn
}

output "vpc_id" {
  description = "VPC id."
  value       = module.networking.vpc_id
}

output "cloudwatch_dashboard_url" {
  description = "Console URL for the CloudWatch dashboard."
  value       = module.monitoring.dashboard_url
}
