output "api_url" {
  description = "Public HTTPS base URL of the dev API."
  value       = module.platform.api_url
}

output "alb_dns_name" {
  description = "ALB DNS name."
  value       = module.platform.alb_dns_name
}

output "ecr_repository_urls" {
  description = "ECR repository URLs, consumed by the CD workflow."
  value       = module.platform.ecr_repository_urls
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = module.platform.ecs_cluster_name
}

output "ecs_service_names" {
  description = "ECS service names."
  value       = module.platform.ecs_service_names
}

output "migrate_task_definition_arn" {
  description = "Flyway migration task definition."
  value       = module.platform.migrate_task_definition_arn
}

output "pipeline_task_definition_arn" {
  description = "Data pipeline task definition."
  value       = module.platform.pipeline_task_definition_arn
}

output "run_task_network_configuration" {
  description = "Network configuration for `aws ecs run-task`."
  value       = module.platform.run_task_network_configuration
}

output "github_deploy_role_arn" {
  description = "Role assumed by GitHub Actions via OIDC."
  value       = module.platform.github_deploy_role_arn
}

output "cloudwatch_dashboard_url" {
  description = "CloudWatch dashboard URL."
  value       = module.platform.cloudwatch_dashboard_url
}
