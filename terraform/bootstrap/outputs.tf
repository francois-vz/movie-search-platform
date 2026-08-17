output "state_bucket" {
  description = "Bucket name to put in each environment's backend block."
  value       = aws_s3_bucket.state.id
}

output "lock_table" {
  description = "DynamoDB table name to put in each environment's backend block."
  value       = aws_dynamodb_table.locks.name
}

output "backend_block" {
  description = "Ready-to-paste backend configuration for an environment root."
  value       = <<-EOT
    terraform {
      backend "s3" {
        bucket         = "${aws_s3_bucket.state.id}"
        key            = "movie-search/<environment>/terraform.tfstate"
        region         = "${var.aws_region}"
        dynamodb_table = "${aws_dynamodb_table.locks.name}"
        encrypt        = true
      }
    }
  EOT
}
