# ---------------------------------------------------------------------------
# IAM: one execution role shared by every task, one task role per service, and
# the GitHub OIDC deployment role.
#
# There are no IAM users and no access keys anywhere in this configuration.
# Tasks receive credentials from the ECS agent; GitHub Actions federates in
# with a short-lived OIDC token.
#
# Execution role vs task role: the execution role belongs to the ECS agent and
# is what pulls images and resolves secrets *before* the container starts. The
# task role is what the application code itself gets. Keeping them apart means
# application code can never read a secret it was not injected with.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    # Stops a confused deputy in another account from assuming these roles.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

# ---- Execution role -------------------------------------------------------

resource "aws_iam_role" "task_execution" {
  name               = "${var.name_prefix}-task-execution"
  description        = "Pulls images and injects secrets for every task in ${var.name_prefix}."
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "task_execution" {
  # GetAuthorizationToken cannot be scoped to a repository.
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = var.ecr_repository_arns
  }

  statement {
    sid    = "WriteTaskLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/ecs/${var.name_prefix}*"]
  }

  # Exactly the secrets this platform defines -- not secretsmanager:* on "*".
  statement {
    sid       = "ReadInjectedSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.secret_arns
  }
}

resource "aws_iam_role_policy" "task_execution" {
  name   = "${var.name_prefix}-task-execution"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution.json
}

# ---- Task roles -----------------------------------------------------------

resource "aws_iam_role" "task" {
  for_each = toset(var.service_names)

  name               = "${var.name_prefix}-task-${each.value}"
  description        = "Application role for the ${each.value} task."
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# ECS Exec, for `aws ecs execute-command` into a running task. The channel is
# brokered by SSM, so the task needs to talk to ssmmessages.
data "aws_iam_policy_document" "task_exec_channel" {
  statement {
    sid    = "SsmExecChannel"
    effect = "Allow"
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "task_exec_channel" {
  for_each = aws_iam_role.task

  name   = "ecs-exec"
  role   = each.value.id
  policy = data.aws_iam_policy_document.task_exec_channel.json
}

# X-Ray, for the services that emit traces. The sampling APIs are read-only and
# cannot be scoped to a resource.
data "aws_iam_policy_document" "xray" {
  statement {
    sid    = "XRayWrite"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
      "xray:GetSamplingStatisticSummaries",
    ]
    resources = ["*"]
  }

  # The ADOT collector publishes application metrics as EMF.
  statement {
    sid       = "PublishMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["MovieSearch", "ECS/ContainerInsights"]
    }
  }
}

resource "aws_iam_role_policy" "xray" {
  for_each = toset([for s in var.service_names : s if contains(var.tracing_service_names, s)])

  name   = "xray"
  role   = aws_iam_role.task[each.value].id
  policy = data.aws_iam_policy_document.xray.json
}

# EFS access for the embedding model cache. Only the embeddings task mounts it.
data "aws_iam_policy_document" "efs" {
  statement {
    sid    = "MountModelCache"
    effect = "Allow"
    actions = [
      "elasticfilesystem:ClientMount",
      "elasticfilesystem:ClientWrite",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "efs" {
  for_each = toset([for s in var.service_names : s if s == "embeddings"])

  name   = "efs-model-cache"
  role   = aws_iam_role.task[each.value].id
  policy = data.aws_iam_policy_document.efs.json
}

# ---- GitHub Actions OIDC --------------------------------------------------

locals {
  enable_oidc = var.github_repository != null

  # Placeholder so the interpolation below stays valid when OIDC is disabled;
  # the resulting list is unused in that case.
  github_repo = coalesce(var.github_repository, "unset")

  # Pinned to this repository. A wildcard here would let any GitHub repository
  # in the world assume the deploy role.
  github_subject_patterns = coalesce(var.github_subject_patterns, [
    "repo:${local.github_repo}:ref:refs/heads/main",
    "repo:${local.github_repo}:environment:dev",
    "repo:${local.github_repo}:environment:prod",
  ])
}

resource "aws_iam_openid_connect_provider" "github" {
  count = local.enable_oidc && var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  # AWS validates GitHub's certificate against its own trust store, but the API
  # still requires a thumbprint. Both of GitHub's current intermediates.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

data "aws_iam_openid_connect_provider" "github" {
  count = local.enable_oidc && !var.create_github_oidc_provider ? 1 : 0

  url = "https://token.actions.githubusercontent.com"
}

locals {
  oidc_provider_arn = local.enable_oidc ? (
    var.create_github_oidc_provider
    ? aws_iam_openid_connect_provider.github[0].arn
    : data.aws_iam_openid_connect_provider.github[0].arn
  ) : null
}

data "aws_iam_policy_document" "github_assume" {
  count = local.enable_oidc ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only workflows on this repository, and only from the branch or
    # environment the CD workflow runs in.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.github_subject_patterns
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  count = local.enable_oidc ? 1 : 0

  name                 = "${var.name_prefix}-github-deploy"
  description          = "Assumed by GitHub Actions to build, push and terraform apply ${var.name_prefix}."
  assume_role_policy   = data.aws_iam_policy_document.github_assume[0].json
  max_session_duration = 3600
}

# Running `terraform apply` means creating networking, RDS, ECS and IAM, so
# this role is necessarily broad. Two guard rails keep it honest: the trust
# policy above restricts *who* can assume it to one repository, and the IAM
# statement below restricts role management to this project's name prefix so a
# compromised workflow cannot mint itself an administrator.
data "aws_iam_policy_document" "github_deploy" {
  count = local.enable_oidc ? 1 : 0

  statement {
    sid       = "TerraformState"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketVersioning"]
    resources = ["arn:aws:s3:::${var.state_bucket_name}"]
  }

  statement {
    sid       = "TerraformStateObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.state_bucket_name}/*"]
  }

  statement {
    sid    = "TerraformLock"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
      "dynamodb:DescribeTable",
    ]
    resources = ["arn:aws:dynamodb:${var.aws_region}:${var.account_id}:table/${var.state_lock_table_name}"]
  }

  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPush"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
    ]
    resources = var.ecr_repository_arns
  }

  statement {
    sid    = "ManageProjectRoles"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:UpdateRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:ListRoleTags",
      "iam:PassRole",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
    ]
    resources = ["arn:aws:iam::${var.account_id}:role/${var.project}-*"]
  }

  statement {
    sid    = "ManageServiceLinkedRoles"
    effect = "Allow"
    actions = [
      "iam:CreateServiceLinkedRole",
      "iam:GetOpenIDConnectProvider",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  count = local.enable_oidc ? 1 : 0

  name   = "deploy"
  role   = aws_iam_role.github_deploy[0].id
  policy = data.aws_iam_policy_document.github_deploy[0].json
}

# Everything that is not IAM or state: VPC, ECS, RDS, ALB, Secrets Manager,
# CloudWatch. PowerUserAccess covers these and explicitly excludes IAM, which
# the scoped statement above grants deliberately.
resource "aws_iam_role_policy_attachment" "github_deploy_power_user" {
  count = local.enable_oidc ? 1 : 0

  role       = aws_iam_role.github_deploy[0].name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}
