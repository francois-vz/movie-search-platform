# ---------------------------------------------------------------------------
# Application Load Balancer, HTTPS termination and access logging.
#
# TLS has two supported shapes:
#   1. certificate_arn  -- bring an existing ACM certificate.
#   2. domain_name + route53_zone_id -- Terraform requests one and validates it
#      over DNS, then points an alias record at the load balancer.
#
# With neither, the module still plans: it serves HTTP only and surfaces the
# gap through the `tls_enabled` output. That keeps `terraform plan` usable as a
# review artifact before a domain exists, which is exactly the position a fresh
# clone of this repository is in.
# ---------------------------------------------------------------------------

data "aws_elb_service_account" "current" {}

locals {
  request_certificate = var.certificate_arn == null && var.domain_name != null && var.route53_zone_id != null
  certificate_arn     = var.certificate_arn != null ? var.certificate_arn : (local.request_certificate ? aws_acm_certificate_validation.this[0].certificate_arn : null)
  tls_enabled         = local.certificate_arn != null

  # Without TLS the public URL is the load balancer's own DNS name over HTTP.
  api_base_url = local.tls_enabled ? "https://${coalesce(var.domain_name, aws_lb.this.dns_name)}" : "http://${aws_lb.this.dns_name}"
}

# ---- Access logs ----------------------------------------------------------

resource "aws_s3_bucket" "access_logs" {
  bucket        = "${var.name_prefix}-alb-logs"
  force_destroy = true

  tags = {
    Name = "${var.name_prefix}-alb-logs"
  }
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    id     = "expire-access-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = var.access_logs_retention_days
    }
  }
}

# Which principal writes ALB access logs depends on the region's age: regions
# opened before August 2022 use a per-region ELB account, newer ones use the
# logdelivery service principal. Granting both keeps this portable.
data "aws_iam_policy_document" "access_logs" {
  statement {
    sid     = "ElbAccountPutObject"
    effect  = "Allow"
    actions = ["s3:PutObject"]

    principals {
      type        = "AWS"
      identifiers = [data.aws_elb_service_account.current.arn]
    }

    resources = ["${aws_s3_bucket.access_logs.arn}/*"]
  }

  statement {
    sid     = "LogDeliveryPutObject"
    effect  = "Allow"
    actions = ["s3:PutObject"]

    principals {
      type        = "Service"
      identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
    }

    resources = ["${aws_s3_bucket.access_logs.arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  policy = data.aws_iam_policy_document.access_logs.json
}

# ---- Load balancer --------------------------------------------------------

resource "aws_lb" "this" {
  name               = substr("${var.name_prefix}-alb", 0, 32)
  load_balancer_type = "application"
  internal           = false
  subnets            = var.public_subnet_ids
  security_groups    = [var.security_group_id]

  enable_deletion_protection = var.deletion_protection
  drop_invalid_header_fields = true
  idle_timeout               = var.idle_timeout

  access_logs {
    bucket  = aws_s3_bucket.access_logs.id
    prefix  = "alb"
    enabled = true
  }

  tags = {
    Name = "${var.name_prefix}-alb"
  }

  depends_on = [aws_s3_bucket_policy.access_logs]
}

resource "aws_lb_target_group" "api" {
  name        = substr("${var.name_prefix}-api", 0, 32)
  port        = var.target_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  # The API is stateless; draining only needs to outlast in-flight requests.
  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = var.health_check_path
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name = "${var.name_prefix}-api"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ---- Certificate ----------------------------------------------------------

resource "aws_acm_certificate" "this" {
  count = local.request_certificate ? 1 : 0

  domain_name       = var.domain_name
  validation_method = "DNS"

  tags = {
    Name = "${var.name_prefix}-cert"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "certificate_validation" {
  for_each = local.request_certificate ? {
    for dvo in aws_acm_certificate.this[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  } : {}

  zone_id         = var.route53_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  count = local.request_certificate ? 1 : 0

  certificate_arn         = aws_acm_certificate.this[0].arn
  validation_record_fqdns = [for r in aws_route53_record.certificate_validation : r.fqdn]
}

# ---- Listeners ------------------------------------------------------------

# With TLS, port 80 exists only to bounce clients to 443.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = local.tls_enabled ? [1] : []

    content {
      type = "redirect"

      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  dynamic "default_action" {
    for_each = local.tls_enabled ? [] : [1]

    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.api.arn
    }
  }
}

resource "aws_lb_listener" "https" {
  count = local.tls_enabled ? 1 : 0

  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = var.ssl_policy
  certificate_arn   = local.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ---- DNS ------------------------------------------------------------------

resource "aws_route53_record" "api" {
  count = var.route53_zone_id != null && var.domain_name != null ? 1 : 0

  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_lb.this.dns_name
    zone_id                = aws_lb.this.zone_id
    evaluate_target_health = true
  }
}
