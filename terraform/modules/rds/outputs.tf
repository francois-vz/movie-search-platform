output "endpoint" {
  description = "Connection endpoint (host:port)."
  value       = aws_db_instance.this.endpoint
}

output "address" {
  description = "Hostname of the instance."
  value       = aws_db_instance.this.address
}

output "port" {
  description = "Port the instance listens on."
  value       = aws_db_instance.this.port
}

output "instance_identifier" {
  description = "DB instance identifier, used as the CloudWatch alarm dimension."
  value       = aws_db_instance.this.identifier
}

output "database_url_secret_arn" {
  description = "Secrets Manager ARN holding the full postgresql:// DSN."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "jdbc_url_secret_arn" {
  description = "Secrets Manager ARN holding the JDBC URL for Flyway."
  value       = aws_secretsmanager_secret.jdbc_url.arn
}

output "password_secret_arn" {
  description = "Secrets Manager ARN holding the master password."
  value       = aws_secretsmanager_secret.db_password.arn
}

output "secret_arns" {
  description = "All database secret ARNs, used to scope the ECS execution role."
  value = [
    aws_secretsmanager_secret.db_password.arn,
    aws_secretsmanager_secret.database_url.arn,
    aws_secretsmanager_secret.jdbc_url.arn,
  ]
}
