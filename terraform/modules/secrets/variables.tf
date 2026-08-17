variable "name_prefix" {
  type        = string
  description = "Prefix for secret names, e.g. movie-search-dev."
}

variable "environment" {
  type        = string
  description = "Deployment environment. Controls the deletion recovery window."
}
