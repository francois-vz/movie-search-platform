output "vpc_id" {
  description = "VPC id."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "VPC CIDR block."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet ids (ALB and NAT only)."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet ids (ECS tasks, RDS, EFS)."
  value       = aws_subnet.private[*].id
}

output "availability_zones" {
  description = "Availability zones in use."
  value       = local.azs
}

output "alb_security_group_id" {
  description = "Security group for the load balancer."
  value       = aws_security_group.alb.id
}

output "ecs_security_group_id" {
  description = "Security group shared by all Fargate tasks."
  value       = aws_security_group.ecs.id
}

output "rds_security_group_id" {
  description = "Security group for the database."
  value       = aws_security_group.rds.id
}

output "efs_security_group_id" {
  description = "Security group for the EFS mount targets."
  value       = aws_security_group.efs.id
}

output "flow_logs_log_group_name" {
  description = "CloudWatch log group receiving VPC Flow Logs."
  value       = aws_cloudwatch_log_group.flow_logs.name
}
