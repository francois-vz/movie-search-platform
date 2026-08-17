output "task_execution_role_arn" {
  description = "Shared ECS execution role: pulls images, injects secrets, writes logs."
  value       = aws_iam_role.task_execution.arn
}

output "task_role_arns" {
  description = "Map of logical service name to its application task role ARN."
  value       = { for k, v in aws_iam_role.task : k => v.arn }
}

output "github_deploy_role_arn" {
  description = "Role GitHub Actions assumes via OIDC. Null when github_repository is unset."
  value       = local.enable_oidc ? aws_iam_role.github_deploy[0].arn : null
}

output "github_oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider in use."
  value       = local.oidc_provider_arn
}
