output "repository_urls" {
  description = "Map of logical image name to repository URL."
  value       = { for k, v in aws_ecr_repository.this : k => v.repository_url }
}

output "repository_arns" {
  description = "Repository ARNs, used to scope the ECS execution role's pull permissions."
  value       = [for r in aws_ecr_repository.this : r.arn]
}

output "repository_names" {
  description = "Map of logical image name to fully-qualified repository name."
  value       = { for k, v in aws_ecr_repository.this : k => v.name }
}
