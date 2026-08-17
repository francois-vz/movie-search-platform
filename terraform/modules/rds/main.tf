# ---------------------------------------------------------------------------
# RDS PostgreSQL 16, private subnets only.
#
# pgvector needs no special provisioning here: RDS ships `vector` as an
# available extension for PostgreSQL 16, and V1__initial_schema.sql already
# runs `CREATE EXTENSION IF NOT EXISTS vector` (and pg_trgm) as the master
# user. The same Flyway migrations therefore apply unchanged to local Postgres
# and to RDS -- see the migrate task in modules/compute.
#
# This module also owns the database credential. Keeping it here rather than in
# modules/secrets avoids a dependency cycle: the connection string needs the
# endpoint, which only exists once the instance is planned.
# ---------------------------------------------------------------------------

locals {
  identifier = "${var.name_prefix}-postgres"

  # Alphanumeric only. RDS rejects '/', '@', '"' and space in a master
  # password, and anything URL-unsafe would have to be percent-encoded in the
  # DSN we hand to asyncpg and Flyway. 40 characters keeps the entropy high.
  password_length = 40
}

resource "random_password" "db" {
  length  = local.password_length
  special = false
}

# ---- Credential secrets ---------------------------------------------------

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${var.name_prefix}/db-password"
  description             = "RDS master password for ${local.identifier}."
  recovery_window_in_days = var.environment == "prod" ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db.result
}

# The applications read a single DATABASE_URL rather than assembling a DSN from
# parts, so the assembled value is what we store.
resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.name_prefix}/database-url"
  description             = "Full PostgreSQL DSN (sslmode=require) for the pipeline and MCP server."
  recovery_window_in_days = var.environment == "prod" ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = format(
    "postgresql://%s:%s@%s:%d/%s?sslmode=require",
    var.db_username,
    random_password.db.result,
    aws_db_instance.this.address,
    aws_db_instance.this.port,
    var.db_name,
  )
}

# JDBC form for the Flyway migration task.
resource "aws_secretsmanager_secret" "jdbc_url" {
  name                    = "${var.name_prefix}/jdbc-url"
  description             = "JDBC URL used by the Flyway migration task."
  recovery_window_in_days = var.environment == "prod" ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "jdbc_url" {
  secret_id = aws_secretsmanager_secret.jdbc_url.id
  secret_string = format(
    "jdbc:postgresql://%s:%d/%s?sslmode=require",
    aws_db_instance.this.address,
    aws_db_instance.this.port,
    var.db_name,
  )
}

# ---- Placement ------------------------------------------------------------

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db"
  subnet_ids = var.subnet_ids

  tags = {
    Name = "${var.name_prefix}-db"
  }
}

resource "aws_db_parameter_group" "this" {
  name        = "${var.name_prefix}-pg16"
  family      = "postgres16"
  description = "PostgreSQL 16 parameters for ${var.name_prefix}."

  # Reject any non-TLS connection. Both asyncpg and the PostgreSQL JDBC driver
  # honour the sslmode=require we put in the stored DSNs.
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Pre-create the export target so retention is managed rather than "never
# expire", which is what RDS defaults to when it creates the group itself.
resource "aws_cloudwatch_log_group" "postgresql" {
  name              = "/aws/rds/instance/${local.identifier}/postgresql"
  retention_in_days = var.log_group_retention_days
}

# ---- Instance -------------------------------------------------------------

resource "aws_db_instance" "this" {
  identifier     = local.identifier
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result
  port     = 5432

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  parameter_group_name   = aws_db_parameter_group.this.name

  # The brief requires the database to be unreachable from the internet.
  publicly_accessible = false
  multi_az            = var.multi_az

  backup_retention_period = var.backup_retention_days
  backup_window           = "02:00-03:00"
  maintenance_window      = "sun:03:30-sun:04:30"
  copy_tags_to_snapshot   = true

  auto_minor_version_upgrade = true
  deletion_protection        = var.deletion_protection

  # dev is disposable; prod keeps a parting snapshot.
  skip_final_snapshot       = !var.deletion_protection
  final_snapshot_identifier = var.deletion_protection ? "${local.identifier}-final-${formatdate("YYYYMMDDhhmmss", timestamp())}" : null

  performance_insights_enabled = var.performance_insights
  monitoring_interval          = var.monitoring_interval
  monitoring_role_arn          = var.monitoring_interval > 0 ? aws_iam_role.enhanced_monitoring[0].arn : null

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  apply_immediately = var.environment != "prod"

  tags = {
    Name = local.identifier
  }

  lifecycle {
    # The snapshot name embeds a timestamp, which would otherwise show up as a
    # diff on every plan.
    ignore_changes = [final_snapshot_identifier]
  }

  depends_on = [aws_cloudwatch_log_group.postgresql]
}

# ---- Enhanced monitoring role (prod only) ---------------------------------

data "aws_iam_policy_document" "enhanced_monitoring_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["monitoring.rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "enhanced_monitoring" {
  count = var.monitoring_interval > 0 ? 1 : 0

  name               = "${var.name_prefix}-rds-monitoring"
  assume_role_policy = data.aws_iam_policy_document.enhanced_monitoring_assume.json
}

resource "aws_iam_role_policy_attachment" "enhanced_monitoring" {
  count = var.monitoring_interval > 0 ? 1 : 0

  role       = aws_iam_role.enhanced_monitoring[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
