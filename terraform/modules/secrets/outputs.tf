output "jwt_signing_key_secret_arn" {
  description = "Secrets Manager ARN of the JWT signing key."
  value       = aws_secretsmanager_secret.jwt_signing_key.arn
}

output "reader_client_secret_arn" {
  description = "Secrets Manager ARN of the reader client secret."
  value       = aws_secretsmanager_secret.reader_client_secret.arn
}

output "admin_client_secret_arn" {
  description = "Secrets Manager ARN of the admin client secret."
  value       = aws_secretsmanager_secret.admin_client_secret.arn
}

output "secret_arns" {
  description = "All application secret ARNs, used to scope the ECS execution role."
  value = [
    aws_secretsmanager_secret.jwt_signing_key.arn,
    aws_secretsmanager_secret.reader_client_secret.arn,
    aws_secretsmanager_secret.admin_client_secret.arn,
  ]
}
