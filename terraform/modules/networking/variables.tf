variable "name_prefix" {
  type        = string
  description = "Prefix for all resource names, e.g. movie-search-dev."
}

variable "aws_region" {
  type        = string
  description = "Region, used to build VPC endpoint service names."
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC."
}

variable "az_count" {
  type        = number
  description = "Number of availability zones to spread subnets across."
}

variable "single_nat_gateway" {
  type        = bool
  description = "Share one NAT gateway across all private subnets instead of one per AZ."
}

variable "flow_logs_retention_days" {
  type        = number
  description = "Retention in days for the VPC Flow Logs log group."
}

variable "api_port" {
  type        = number
  description = "Port the .NET API listens on; opened from the ALB to the tasks."
}

variable "mcp_port" {
  type        = number
  description = "Port the MCP server listens on; opened task-to-task."
}

variable "embeddings_port" {
  type        = number
  description = "Port the embedding server listens on; opened task-to-task."
}
