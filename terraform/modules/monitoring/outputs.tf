output "log_group_names" {
  description = "Map of task name to CloudWatch log group name, consumed by the task definitions."
  value       = { for k, v in aws_cloudwatch_log_group.tasks : k => v.name }
}

output "log_group_arns" {
  description = "Task log group ARNs."
  value       = [for v in aws_cloudwatch_log_group.tasks : v.arn]
}

output "sns_topic_arn" {
  description = "Alarm topic ARN, or null when alarm_email is unset."
  value       = var.alarm_email != null ? aws_sns_topic.alarms[0].arn : null
}

output "dashboard_name" {
  description = "CloudWatch dashboard name."
  value       = aws_cloudwatch_dashboard.this.dashboard_name
}

output "dashboard_url" {
  description = "Console URL for the dashboard."
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.this.dashboard_name}"
}
