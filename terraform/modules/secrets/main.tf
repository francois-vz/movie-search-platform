# ---------------------------------------------------------------------------
# Application secrets in AWS Secrets Manager.
#
# The database credential is not here: it is generated and stored by the rds
# module, which is the only place that knows the endpoint needed to assemble a
# connection string. This module owns the secrets the application itself signs
# and checks tokens with.
#
# Values are generated, never supplied as variables, so no credential is ever
# written in a tfvars file or a CI variable. They do land in Terraform state,
# which is why the S3 backend is encrypted and versioned.
# ---------------------------------------------------------------------------

locals {
  # dev is torn down and rebuilt often; a recovery window would make a secret
  # name unusable for days after a destroy.
  recovery_window_days = var.environment == "prod" ? 30 : 0
}

# ---- JWT signing key ------------------------------------------------------

resource "random_password" "jwt_signing_key" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "jwt_signing_key" {
  name                    = "${var.name_prefix}/jwt-signing-key"
  description             = "HMAC key the API uses to sign and validate JWTs."
  recovery_window_in_days = local.recovery_window_days
}

resource "aws_secretsmanager_secret_version" "jwt_signing_key" {
  secret_id     = aws_secretsmanager_secret.jwt_signing_key.id
  secret_string = random_password.jwt_signing_key.result
}

# ---- Client credentials ---------------------------------------------------

resource "random_password" "reader_client_secret" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "reader_client_secret" {
  name                    = "${var.name_prefix}/auth-reader-client-secret"
  description             = "client_secret for the reader role (search only)."
  recovery_window_in_days = local.recovery_window_days
}

resource "aws_secretsmanager_secret_version" "reader_client_secret" {
  secret_id     = aws_secretsmanager_secret.reader_client_secret.id
  secret_string = random_password.reader_client_secret.result
}

resource "random_password" "admin_client_secret" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "admin_client_secret" {
  name                    = "${var.name_prefix}/auth-admin-client-secret"
  description             = "client_secret for the admin role (stats and all endpoints)."
  recovery_window_in_days = local.recovery_window_days
}

resource "aws_secretsmanager_secret_version" "admin_client_secret" {
  secret_id     = aws_secretsmanager_secret.admin_client_secret.id
  secret_string = random_password.admin_client_secret.result
}
