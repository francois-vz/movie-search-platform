variable "name_prefix" {
  type        = string
  description = "Prefix for repository names, e.g. movie-search-dev."
}

variable "repository_names" {
  type        = list(string)
  description = "Logical image names to create repositories for."
}

variable "image_retention_count" {
  type        = number
  description = "Number of tagged images to retain per repository."
}

variable "image_tag_mutability" {
  type        = string
  description = "IMMUTABLE keeps a tag pinned to one image. Requires CD to tag by git SHA."
  default     = "IMMUTABLE"

  validation {
    condition     = contains(["IMMUTABLE", "MUTABLE"], var.image_tag_mutability)
    error_message = "image_tag_mutability must be IMMUTABLE or MUTABLE."
  }
}

variable "force_delete" {
  type        = bool
  description = "Allow `terraform destroy` to remove repositories that still contain images."
  default     = true
}
