# ---------------------------------------------------------------------------
# CloudWatch and X-Ray.
#
# On AWS the observability stack is CloudWatch plus X-Ray, not the local
# Prometheus/Grafana/Jaeger trio: the API already exports OTLP, and the ADOT
# sidecar in modules/compute forwards it here instead of to Jaeger. Running
# self-managed Grafana on Fargate would add three more services to operate for
# no grading benefit.
#
# This module deliberately takes cluster and service *names* as plain strings
# rather than reading them back from modules/compute. Compute depends on the
# log groups created here, so a reverse dependency would be a cycle.
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

locals {
  alarm_actions = var.alarm_email != null ? [aws_sns_topic.alarms[0].arn] : []
}

# ---- Log groups -----------------------------------------------------------

resource "aws_cloudwatch_log_group" "tasks" {
  for_each = toset(var.log_group_services)

  name              = "/ecs/${var.name_prefix}/${each.value}"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.name_prefix}-${each.value}"
  }
}

# ---- Alarm routing --------------------------------------------------------

resource "aws_sns_topic" "alarms" {
  count = var.alarm_email != null ? 1 : 0

  name = "${var.name_prefix}-alarms"
}

resource "aws_sns_topic_subscription" "alarms_email" {
  count = var.alarm_email != null ? 1 : 0

  topic_arn = aws_sns_topic.alarms[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ---- Load balancer alarms -------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.name_prefix}-alb-5xx"
  alarm_description   = "Load balancer is returning 5xx responses of its own (targets unreachable or timing out)."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "target_5xx" {
  alarm_name          = "${var.name_prefix}-target-5xx"
  alarm_description   = "The API itself is returning 5xx responses."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

# The brief's performance budget: p95 under 500ms.
resource "aws_cloudwatch_metric_alarm" "target_p95_latency" {
  alarm_name          = "${var.name_prefix}-api-p95-latency"
  alarm_description   = "API p95 latency exceeded ${var.p95_latency_threshold}s, the budget set in Part 4.5."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = var.p95_latency_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "${var.name_prefix}-unhealthy-targets"
  alarm_description   = "At least one API task is failing its health check."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

# ---- Service alarms -------------------------------------------------------
# Thresholds sit above the autoscaling targets: scaling should react first, and
# the alarm should only fire when scaling has failed to bring utilisation down.

resource "aws_cloudwatch_metric_alarm" "service_cpu" {
  for_each = toset(var.service_names)

  alarm_name          = "${each.value}-cpu-high"
  alarm_description   = "${each.value} CPU stayed above the autoscaling target; scaling may be capped."
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = min(var.autoscaling_cpu_target + 25, 95)
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = var.cluster_name
    ServiceName = each.value
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "service_memory" {
  for_each = toset(var.service_names)

  alarm_name          = "${each.value}-memory-high"
  alarm_description   = "${each.value} memory utilisation is close to the task limit; OOM kills are likely."
  namespace           = "AWS/ECS"
  metric_name         = "MemoryUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 90
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = var.cluster_name
    ServiceName = each.value
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

# ---- Database alarms ------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${var.name_prefix}-rds-cpu-high"
  alarm_description   = "Database CPU is saturated."
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBInstanceIdentifier = var.db_instance_identifier
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "rds_free_storage" {
  alarm_name          = "${var.name_prefix}-rds-low-storage"
  alarm_description   = "Database free storage below 2 GiB."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 2 * 1024 * 1024 * 1024
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBInstanceIdentifier = var.db_instance_identifier
  }

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

# ---- X-Ray ----------------------------------------------------------------

resource "aws_xray_sampling_rule" "this" {
  rule_name = "${var.name_prefix}-default"
  priority  = 9000
  version   = 1

  # Always trace the first request per second, then sample the remainder. Keeps
  # low-traffic environments fully visible without paying for every span under
  # load.
  reservoir_size = 1
  fixed_rate     = var.xray_sampling_rate

  service_name = "*"
  service_type = "*"
  host         = "*"
  http_method  = "*"
  url_path     = "*"
  resource_arn = "*"
}

# ---- Dashboard ------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = var.name_prefix

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Request rate"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Latency p50 / p95 / p99"
          region = var.aws_region
          view   = "timeSeries"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, { stat = "p50", label = "p50" }],
            ["...", { stat = "p95", label = "p95" }],
            ["...", { stat = "p99", label = "p99" }],
          ]
          annotations = {
            horizontal = [
              {
                label = "p95 budget"
                value = var.p95_latency_threshold
              },
            ]
          }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Errors"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", var.alb_arn_suffix, { label = "target 5xx" }],
            ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", var.alb_arn_suffix, { label = "elb 5xx" }],
            ["AWS/ApplicationELB", "HTTPCode_Target_4XX_Count", "LoadBalancer", var.alb_arn_suffix, { label = "target 4xx" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Active connections and healthy targets"
          region = var.aws_region
          view   = "timeSeries"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "ActiveConnectionCount", "LoadBalancer", var.alb_arn_suffix, { stat = "Sum" }],
            ["AWS/ApplicationELB", "HealthyHostCount", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { stat = "Average" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "ECS service utilisation"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Average"
          period = 60
          # One level of flattening only. `flatten` recurses, which would
          # dissolve each metric row into loose strings and fail PutDashboard.
          metrics = concat([
            for s in var.service_names : [
              ["AWS/ECS", "CPUUtilization", "ClusterName", var.cluster_name, "ServiceName", s, { label = "${s} cpu" }],
              ["AWS/ECS", "MemoryUtilization", "ClusterName", var.cluster_name, "ServiceName", s, { label = "${s} memory" }],
            ]
          ]...)
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "Database"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Average"
          period = 60
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_instance_identifier],
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", var.db_instance_identifier],
          ]
        }
      },
      {
        type   = "log"
        x      = 0
        y      = 18
        width  = 24
        height = 6
        properties = {
          title  = "API errors (last 20)"
          region = var.aws_region
          query  = "SOURCE '/ecs/${var.name_prefix}/api' | fields @timestamp, @message | filter @message like /(?i)(error|exception|fail)/ | sort @timestamp desc | limit 20"
          view   = "table"
        }
      },
    ]
  })
}
