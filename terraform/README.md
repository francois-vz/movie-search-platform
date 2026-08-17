# Terraform — AWS Deployment

Deploys the Movie Search Platform to AWS on **ECS Fargate**.

Step-by-step deployment instructions live in the root
[`README.md` §12](../README.md#12-terraform-deployment). This file covers the
module layout and the design decisions behind it.

> ⚠️ Validated with `terraform fmt -check`, `terraform validate` and
> `terraform init -backend=false` on all four roots. **Never applied against a
> real AWS account.**

## Why ECS Fargate, not EKS

The brief allows either and asks for a justification.

This platform is five long-lived containers and two run-to-completion jobs.
Fargate removes both the control-plane cost and the node lifecycle: there are no
instances to patch, scale or upgrade, and a task definition is the whole
deployment unit. The integrations this design leans on — ALB target groups,
Secrets Manager injection into containers, CloudWatch log groups, application
auto-scaling, IAM task roles — are first-party in ECS rather than add-ons that
have to be installed and version-managed.

EKS would buy Kubernetes portability, a richer scheduling model and a large
ecosystem. Nothing in this workload needs any of it, and the price is a cluster
upgrade cadence plus the add-on surface (CNI, CSI, load balancer controller,
external-secrets) that a single engineer would then own.

## Layout

```
terraform/
├── bootstrap/            # S3 state bucket + DynamoDB lock table (once per account)
├── modules/
│   ├── networking/       # VPC, public/private subnets, NAT, SGs, VPC Flow Logs
│   ├── compute/          # ECS cluster, task definitions, services, auto-scaling
│   ├── rds/              # PostgreSQL 16 + pgvector, private, encrypted
│   ├── ecr/              # tag-immutable repositories, scan-on-push, lifecycle policy
│   ├── alb/              # ALB, ACM certificate, HTTPS listener, HTTP→HTTPS redirect
│   ├── iam/              # task/execution roles, GitHub OIDC deploy role
│   ├── monitoring/       # CloudWatch dashboard + alarms, X-Ray sampling rule
│   └── secrets/          # Secrets Manager entries
├── environments/
│   ├── dev/              # root: backend, provider, cost-shaped sizing
│   └── prod/             # root: backend, provider, production sizing
├── main.tf               # composition module — wires the modules together
├── variables.tf
├── outputs.tf
├── versions.tf
└── README.md
```

**This directory is a module, not a root.** It declares no provider and no
backend, so it cannot be applied directly. The roots are
`environments/dev` and `environments/prod`, which own the S3 backend, the
provider (including `default_tags`) and the per-environment sizing. That split
keeps the composition identical across environments — the only differences are
input values, so a dev plan is a meaningful rehearsal of a prod plan.

`bootstrap/` is the one exception: it keeps state locally, because it is what
creates the S3 bucket and DynamoDB table the other roots store state in.

## Environment sizing

| | dev | prod |
| --- | --- | --- |
| NAT gateways | 1 (shared) | one per AZ |
| RDS | `db.t4g.micro`, single-AZ | multi-AZ |
| RDS backups | 1 day | extended |
| Deletion protection | off | on |
| API tasks | 2, scaling to 4 | higher floor and ceiling |
| Log retention | 14 days | longer |

Dev keeps two API tasks despite the cost focus, so a rolling deployment never
drops to zero.

## Requirements checklist (§6.2 of the brief)

- [x] **Secrets via AWS Secrets Manager, none hardcoded** — `modules/secrets`
      holds application secrets; `modules/rds` owns the database credential and
      the assembled `DATABASE_URL`. Both are injected into task definitions as
      `secrets` (ARN references resolved by the ECS agent), never `environment`,
      so no plaintext value reaches the task definition or CloudWatch.
- [x] **Tasks use IAM roles, no access keys** — `modules/iam` defines separate
      execution and task roles per service. GitHub Actions authenticates with
      OIDC against a deploy role scoped to the repository; no long-lived
      credentials exist anywhere.
- [x] **RDS in private subnets only** — dedicated subnet group over the private
      subnets, `publicly_accessible = false`, `storage_encrypted = true`. Its
      security group (defined in `modules/networking` alongside the others)
      admits only the ECS task security group on 5432 and has no egress rule at
      all, since the database never originates a connection.
- [x] **ALB with HTTPS (ACM)** — `:443` listener with a configurable
      `ssl_policy`; `:80` exists solely to redirect. Supply an existing
      `certificate_arn`, or `domain_name` + `route53_zone_id` to have Terraform
      request and DNS-validate one.
- [x] **Auto-scaling (CPU and memory)** — two target-tracking
      `aws_appautoscaling_policy` resources per scalable service, on
      `ECSServiceAverageCPUUtilization` and `ECSServiceAverageMemoryUtilization`.
- [x] **VPC Flow Logs** — enabled in `modules/networking` to CloudWatch, with
      configurable retention.
- [x] **S3 backend + DynamoDB locking** — created by `bootstrap/` (versioned,
      AES256-encrypted, public access blocked, noncurrent versions expiring at
      90 days; the lock table has point-in-time recovery). Both resources set
      `prevent_destroy`. The roots set `dynamodb_table` *and* `use_lockfile`, so
      locking keeps working across the Terraform 1.11 deprecation of the former.
- [x] **Tags: Environment, Project, ManagedBy** — `default_tags` on the provider
      in each root, so every taggable resource inherits them.

## Notes

- **Tag immutability.** ECR repositories default to `IMMUTABLE`, so a tag names
  exactly one image forever. CD therefore tags by 12-character git SHA, and a
  rollback is a redeploy of an older SHA rather than a re-tag.
- **Log group ownership.** Log groups are created by `modules/monitoring` and
  consumed by `modules/compute`, and ECS names are derived in `main.tf` locals
  rather than read back from `module.compute`. This keeps the dependency
  one-directional: monitoring can alarm on service names without depending on
  compute.
- **Atlas is not deployed.** The Part 5 bonus is a local Compose service only.
- **`backend.hcl` and `terraform.tfvars` are gitignored** — the bucket name
  embeds the AWS account id. Copy the `.example` files and fill them in.
