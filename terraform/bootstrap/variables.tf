variable "aws_region" {
  type        = string
  description = "Region hosting the state bucket and lock table."
}

variable "project" {
  type        = string
  description = "Project name, used to build the bucket and table names."
  default     = "movie-search"
}
