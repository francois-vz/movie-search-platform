output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "cluster_arn" {
  description = "ECS cluster ARN."
  value       = aws_ecs_cluster.this.arn
}

output "service_names" {
  description = "Map of logical name to running ECS service name."
  value = {
    api        = aws_ecs_service.api.name
    mcp-server = aws_ecs_service.mcp.name
    embeddings = aws_ecs_service.embeddings.name
  }
}

output "service_discovery_namespace" {
  description = "Private DNS namespace used for service-to-service calls."
  value       = aws_service_discovery_private_dns_namespace.this.name
}

output "mcp_server_url" {
  description = "Internal URL the API uses to reach the MCP server."
  value       = local.mcp_url
}

output "pipeline_task_definition_arn" {
  description = "Task definition for the one-shot data pipeline."
  value       = aws_ecs_task_definition.pipeline.arn
}

output "migrate_task_definition_arn" {
  description = "Task definition for the Flyway migration job."
  value       = aws_ecs_task_definition.migrate.arn
}

output "pipeline_task_family" {
  description = "Family name for `aws ecs run-task --task-definition`."
  value       = aws_ecs_task_definition.pipeline.family
}

output "migrate_task_family" {
  description = "Family name for `aws ecs run-task --task-definition`."
  value       = aws_ecs_task_definition.migrate.family
}

output "efs_file_system_id" {
  description = "EFS file system caching the embedding model."
  value       = aws_efs_file_system.models.id
}
