output "alb_arn" {
  description = "Load balancer ARN."
  value       = aws_lb.this.arn
}

output "alb_dns_name" {
  description = "Load balancer DNS name."
  value       = aws_lb.this.dns_name
}

output "alb_zone_id" {
  description = "Hosted zone id of the load balancer, for alias records."
  value       = aws_lb.this.zone_id
}

output "alb_arn_suffix" {
  description = "ARN suffix used as the CloudWatch dimension for ALB metrics."
  value       = aws_lb.this.arn_suffix
}

output "target_group_arn" {
  description = "Target group the API service registers into."
  value       = aws_lb_target_group.api.arn
}

output "target_group_arn_suffix" {
  description = "Target group ARN suffix used as a CloudWatch dimension."
  value       = aws_lb_target_group.api.arn_suffix
}

output "https_listener_arn" {
  description = "HTTPS listener ARN, or null when no certificate is configured. Services depend on this so tasks are not registered before a listener exists."
  value       = local.tls_enabled ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
}

output "certificate_arn" {
  description = "Certificate actually in use (supplied or requested)."
  value       = local.certificate_arn
}

output "tls_enabled" {
  description = "False when neither certificate_arn nor domain_name+route53_zone_id was supplied; the listener is plain HTTP in that case."
  value       = local.tls_enabled
}

output "api_base_url" {
  description = "Base URL clients should call."
  value       = local.api_base_url
}
