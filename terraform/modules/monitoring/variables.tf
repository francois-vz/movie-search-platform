variable "name_prefix" {
  type        = string
  description = "Prefix for resource names, e.g. movie-search-dev."
}

variable "aws_region" {
  type        = string
  description = "Region, used for dashboard widgets and the console URL."
}

variable "log_group_services" {
  type        = list(string)
  description = "Task names to create log groups for, including run-to-completion tasks."
}

variable "log_retention_days" {
  type        = number
  description = "Retention in days for the task log groups."
}

variable "cluster_name" {
  type        = string
  description = "ECS cluster name, used as an alarm dimension. Passed as a string to avoid a cycle with modules/compute."
}

variable "service_names" {
  type        = list(string)
  description = "ECS service names to alarm and chart."
}

variable "alb_arn_suffix" {
  type        = string
  description = "Load balancer ARN suffix (CloudWatch dimension)."
}

variable "target_group_arn_suffix" {
  type        = string
  description = "Target group ARN suffix (CloudWatch dimension)."
}

variable "db_instance_identifier" {
  type        = string
  description = "RDS instance identifier (CloudWatch dimension)."
}

variable "alarm_email" {
  type        = string
  description = "Address subscribed to the alarm topic. Null creates no topic and no alarm actions."
  default     = null
}

variable "p95_latency_threshold" {
  type        = number
  description = "Seconds. Alarm fires above this p95."
  default     = 0.5
}

variable "xray_sampling_rate" {
  type        = number
  description = "Fraction of requests sampled beyond the reservoir."
  default     = 0.1
}

variable "autoscaling_cpu_target" {
  type        = number
  description = "Autoscaling CPU target. The CPU alarm threshold is set above it."
  default     = 60
}
