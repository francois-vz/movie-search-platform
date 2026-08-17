# ---------------------------------------------------------------------------
# ECS Fargate: cluster, service discovery, the three long-lived services and
# the two run-to-completion task definitions.
#
# Service-to-service addressing mirrors Docker Compose. Locally the API reaches
# the MCP server at http://mcp-server:8000 because Compose provides DNS on the
# user-defined network; here Cloud Map provides the same shape at
# http://mcp-server.<namespace>:8000, so no application configuration differs
# between the two environments beyond the hostname suffix.
# ---------------------------------------------------------------------------

locals {
  namespace = "${var.name_prefix}.local"

  mcp_url           = "http://${var.service_names["mcp-server"]}.${local.namespace}:${var.mcp_port}"
  embeddings_url    = "http://${var.service_names["embeddings"]}.${local.namespace}:${var.embeddings_port}"
  otlp_endpoint     = "http://localhost:4317"
  ollama_model_path = "/root/.ollama"

  # Indexed rather than dot-accessed below: "mcp-server" is not a valid HCL
  # attribute name.
  image = {
    api        = "${var.repository_urls["api"]}:${var.image_tag}"
    mcp-server = "${var.repository_urls["mcp-server"]}:${var.image_tag}"
    pipeline   = "${var.repository_urls["pipeline"]}:${var.image_tag}"
    migrate    = "${var.repository_urls["migrate"]}:${var.image_tag}"
  }

  # Every task ships stdout to its own CloudWatch log group.
  log_config = {
    for name, group in var.log_group_names : name => {
      logDriver = "awslogs"
      options = {
        awslogs-group         = group
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ecs"
      }
    }
  }

  # Shared by the Python services so their embedding client is configured
  # identically to the Compose stack.
  embedding_env = [
    { name = "EMBEDDING_BASE_URL", value = local.embeddings_url },
    { name = "EMBEDDING_MODEL", value = var.embedding_model },
    { name = "EMBEDDING_DIM", value = tostring(var.embedding_dim) },
    { name = "EMBEDDING_BATCH_SIZE", value = tostring(var.embedding_batch_size) },
  ]
}

# ---- Cluster --------------------------------------------------------------

resource "aws_ecs_cluster" "this" {
  name = var.cluster_name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  configuration {
    execute_command_configuration {
      logging = "DEFAULT"
    }
  }

  tags = {
    Name = var.cluster_name
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

# ---- Service discovery ----------------------------------------------------

resource "aws_service_discovery_private_dns_namespace" "this" {
  name        = local.namespace
  description = "Internal DNS for ${var.name_prefix} services."
  vpc         = var.vpc_id
}

resource "aws_service_discovery_service" "mcp" {
  name = var.service_names["mcp-server"]

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

resource "aws_service_discovery_service" "embeddings" {
  name = var.service_names["embeddings"]

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

# ---- Model cache ----------------------------------------------------------
# Ollama pulls nomic-embed-text on first boot. Without shared storage every
# task replacement re-downloads it, which turns a rolling deploy into minutes
# of unavailability. EFS makes the pull a one-off per environment.

resource "aws_efs_file_system" "models" {
  creation_token = "${var.name_prefix}-models"
  encrypted      = true

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = {
    Name = "${var.name_prefix}-models"
  }
}

resource "aws_efs_mount_target" "models" {
  count = length(var.private_subnet_ids)

  file_system_id  = aws_efs_file_system.models.id
  subnet_id       = var.private_subnet_ids[count.index]
  security_groups = [var.efs_security_group_id]
}

resource "aws_efs_access_point" "models" {
  file_system_id = aws_efs_file_system.models.id

  # Ollama runs as root in the upstream image and writes to /root/.ollama.
  posix_user {
    uid = 0
    gid = 0
  }

  root_directory {
    path = "/ollama"

    creation_info {
      owner_uid   = 0
      owner_gid   = 0
      permissions = "0755"
    }
  }

  tags = {
    Name = "${var.name_prefix}-models"
  }
}

# ---- Task definitions -----------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = var.service_names["api"]
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arns["api"]

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = local.image["api"]
      essential = true

      portMappings = [
        {
          containerPort = var.api_port
          protocol      = "tcp"
        },
      ]

      environment = [
        { name = "ASPNETCORE_ENVIRONMENT", value = "Production" },
        { name = "ASPNETCORE_URLS", value = "http://+:${var.api_port}" },
        { name = "MCP_CLIENT", value = "mcp" },
        { name = "MCP_SERVER_URL", value = local.mcp_url },
        { name = "JWT_ISSUER", value = var.jwt_issuer },
        { name = "JWT_AUDIENCE", value = var.jwt_audience },
        { name = "JWT_EXPIRY_MINUTES", value = tostring(var.jwt_expiry_minutes) },
        { name = "AUTH_READER_CLIENT_ID", value = var.reader_client_id },
        { name = "AUTH_ADMIN_CLIENT_ID", value = var.admin_client_id },
        { name = "CACHE_TTL_SECONDS", value = tostring(var.cache_ttl_seconds) },
        { name = "RATE_LIMIT_PER_MINUTE", value = tostring(var.rate_limit_per_minute) },
        { name = "REQUEST_TIMEOUT_SECONDS", value = tostring(var.request_timeout_seconds) },
        # The sidecar below, not Jaeger.
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = local.otlp_endpoint },
        { name = "OTEL_SERVICE_NAME", value = var.service_names["api"] },
        { name = "API_PUBLIC_URL", value = var.api_public_url },
      ]

      # Resolved by the ECS agent before the container starts; the value never
      # appears in the task definition or in `terraform show`.
      secrets = [
        { name = "JWT_SIGNING_KEY", valueFrom = var.jwt_signing_key_secret_arn },
        { name = "AUTH_READER_CLIENT_SECRET", valueFrom = var.reader_secret_arn },
        { name = "AUTH_ADMIN_CLIENT_SECRET", valueFrom = var.admin_secret_arn },
      ]

      dependsOn = [
        { containerName = "otel-collector", condition = "START" },
      ]

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:${var.api_port}/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      logConfiguration = local.log_config["api"]
    },
    {
      name      = "otel-collector"
      image     = var.otel_collector_image
      essential = false

      command = ["--config=/etc/ecs/ecs-default-config.yaml"]

      environment = [
        { name = "AWS_REGION", value = var.aws_region },
      ]

      logConfiguration = local.log_config["api"]
    },
  ])

  tags = {
    Name = var.service_names["api"]
  }
}

resource "aws_ecs_task_definition" "mcp" {
  family                   = var.service_names["mcp-server"]
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.mcp_cpu
  memory                   = var.mcp_memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arns["mcp-server"]

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "mcp-server"
      image     = local.image["mcp-server"]
      essential = true

      portMappings = [
        {
          containerPort = var.mcp_port
          protocol      = "tcp"
        },
      ]

      environment = concat(
        [
          { name = "MCP_HOST", value = "0.0.0.0" },
          { name = "MCP_PORT", value = tostring(var.mcp_port) },
          { name = "MCP_TRANSPORT", value = var.mcp_transport },
          { name = "MCP_LOG_LEVEL", value = var.log_level },
          { name = "DB_POOL_MIN_SIZE", value = tostring(var.db_pool_min_size) },
          { name = "DB_POOL_MAX_SIZE", value = tostring(var.db_pool_max_size) },
          { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = local.otlp_endpoint },
          { name = "OTEL_SERVICE_NAME", value = var.service_names["mcp-server"] },
        ],
        local.embedding_env,
      )

      secrets = [
        { name = "DATABASE_URL", valueFrom = var.database_url_secret_arn },
      ]

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:${var.mcp_port}/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      logConfiguration = local.log_config["mcp-server"]
    },
  ])

  tags = {
    Name = var.service_names["mcp-server"]
  }
}

resource "aws_ecs_task_definition" "embeddings" {
  family                   = var.service_names["embeddings"]
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.embeddings_cpu
  memory                   = var.embeddings_memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arns["embeddings"]

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  volume {
    name = "ollama-models"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.models.id
      transit_encryption = "ENABLED"

      authorization_config {
        access_point_id = aws_efs_access_point.models.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "embeddings"
      image     = var.embeddings_image
      essential = true

      # Same start-serve-then-pull dance as the Compose service. The pull is a
      # no-op once the model is on the EFS volume.
      entryPoint = ["/bin/sh", "-c"]
      command = [
        "ollama serve & until ollama list >/dev/null 2>&1; do sleep 1; done; ollama pull ${var.embedding_model}; wait",
      ]

      portMappings = [
        {
          containerPort = var.embeddings_port
          protocol      = "tcp"
        },
      ]

      environment = [
        { name = "OLLAMA_HOST", value = "0.0.0.0:${var.embeddings_port}" },
        { name = "OLLAMA_MODELS", value = "${local.ollama_model_path}/models" },
      ]

      mountPoints = [
        {
          sourceVolume  = "ollama-models"
          containerPath = local.ollama_model_path
          readOnly      = false
        },
      ]

      healthCheck = {
        command  = ["CMD-SHELL", "ollama list | grep -q ${var.embedding_model} || exit 1"]
        interval = 30
        timeout  = 10
        retries  = 5
        # First boot has to download the model over NAT.
        startPeriod = 300
      }

      logConfiguration = local.log_config["embeddings"]
    },
  ])

  tags = {
    Name = var.service_names["embeddings"]
  }
}

# Run-to-completion. Not a service: invoked with `aws ecs run-task`, which is
# what the CD workflow does after an image push.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name_prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arns["migrate"]

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "migrate"
      image     = local.image["migrate"]
      essential = true

      command = ["migrate"]

      environment = [
        { name = "FLYWAY_USER", value = var.db_username },
        { name = "FLYWAY_CONNECT_RETRIES", value = "10" },
      ]

      secrets = [
        { name = "FLYWAY_URL", valueFrom = var.jdbc_url_secret_arn },
        { name = "FLYWAY_PASSWORD", valueFrom = var.db_password_secret_arn },
      ]

      logConfiguration = local.log_config["migrate"]
    },
  ])

  tags = {
    Name = "${var.name_prefix}-migrate"
  }
}

resource "aws_ecs_task_definition" "pipeline" {
  family                   = "${var.name_prefix}-pipeline"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.pipeline_cpu
  memory                   = var.pipeline_memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arns["pipeline"]

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "pipeline"
      image     = local.image["pipeline"]
      essential = true

      environment = concat(
        [
          { name = "PIPELINE_VERSION", value = var.pipeline_version },
          { name = "PIPELINE_LOG_LEVEL", value = var.log_level },
          { name = "OTEL_SERVICE_NAME", value = "${var.name_prefix}-pipeline" },
        ],
        local.embedding_env,
      )

      secrets = [
        { name = "DATABASE_URL", valueFrom = var.database_url_secret_arn },
      ]

      logConfiguration = local.log_config["pipeline"]
    },
  ])

  tags = {
    Name = "${var.name_prefix}-pipeline"
  }
}

# ---- Services -------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name            = var.service_names["api"]
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  enable_execute_command = true
  propagate_tags         = "SERVICE"

  # A first apply runs before any image exists in ECR. Blocking on steady state
  # would turn that into a 15-minute timeout instead of a clear "task failed to
  # pull" event, so CD pushes images first and this stays false.
  wait_for_steady_state = false

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.api_target_group_arn
    container_name   = "api"
    container_port   = var.api_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  health_check_grace_period_seconds = 90

  tags = {
    Name = var.service_names["api"]
  }

  lifecycle {
    # Autoscaling owns desired_count after creation.
    ignore_changes = [desired_count]
  }
}

resource "aws_ecs_service" "mcp" {
  name            = var.service_names["mcp-server"]
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.mcp.arn
  desired_count   = var.mcp_desired_count
  launch_type     = "FARGATE"

  enable_execute_command = true
  propagate_tags         = "SERVICE"
  wait_for_steady_state  = false

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.mcp.arn
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name = var.service_names["mcp-server"]
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

resource "aws_ecs_service" "embeddings" {
  name            = var.service_names["embeddings"]
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.embeddings.arn
  desired_count   = var.embeddings_desired_count
  launch_type     = "FARGATE"

  enable_execute_command = true
  propagate_tags         = "SERVICE"
  wait_for_steady_state  = false

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.embeddings.arn
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name = var.service_names["embeddings"]
  }

  depends_on = [aws_efs_mount_target.models]

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ---- Autoscaling ----------------------------------------------------------
# Target tracking on both CPU and memory, as the brief requires. The two
# policies coexist: Application Auto Scaling takes the larger of the two
# desired counts, so whichever resource is under pressure wins.

locals {
  scalable_services = {
    api = {
      service_name = aws_ecs_service.api.name
      min_capacity = var.api_min_capacity
      max_capacity = var.api_max_capacity
    }
    mcp-server = {
      service_name = aws_ecs_service.mcp.name
      min_capacity = var.mcp_min_capacity
      max_capacity = var.mcp_max_capacity
    }
    embeddings = {
      service_name = aws_ecs_service.embeddings.name
      min_capacity = var.embeddings_min_capacity
      max_capacity = var.embeddings_max_capacity
    }
  }
}

resource "aws_appautoscaling_target" "this" {
  for_each = local.scalable_services

  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${each.value.service_name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = each.value.min_capacity
  max_capacity       = each.value.max_capacity
}

resource "aws_appautoscaling_policy" "cpu" {
  for_each = local.scalable_services

  name               = "${each.value.service_name}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.this[each.key].service_namespace
  resource_id        = aws_appautoscaling_target.this[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.this[each.key].scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value = var.autoscaling_cpu_target

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }

    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "memory" {
  for_each = local.scalable_services

  name               = "${each.value.service_name}-memory"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.this[each.key].service_namespace
  resource_id        = aws_appautoscaling_target.this[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.this[each.key].scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value = var.autoscaling_memory_target

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }

    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
