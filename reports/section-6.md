# Section 6 — Infrastructure & DevOps

Living report for Part 6: local orchestration (6.1), Terraform on AWS (6.2) and
CI/CD (6.3). Terraform lives in [`terraform/`](../terraform), with usage in
[`terraform/README.md`](../terraform/README.md).

The plan this part was built from: [plans/part-6-infrastructure-devops.plan.md](plans/part-6-infrastructure-devops.plan.md).

**Status:** Compose, all eight Terraform modules, both environment roots and
both workflows are implemented. `terraform validate` passes on every root; the
dev `plan` is the reviewable artifact (see "Verification" below).

---

## 6.1 Docker Compose

The nine required services were already present. This section closed the gaps
the brief calls out explicitly: *"All services must use health checks and
`depends_on` with `condition: service_healthy`."*

| Change | Why |
| ------ | --- |
| Healthchecks on `prometheus`, `grafana`, `jaeger` | They were the three services without one, so nothing could depend on them properly. |
| `grafana` now waits on `prometheus` being *healthy* | It used the short `depends_on: [prometheus]` form, which only waits for the container to be created. |
| `api` now waits on `jaeger` being healthy | The API exports OTLP to Jaeger on startup; racing it produced dropped spans. |
| Pinned every `:latest` tag | `docker compose up --build` has to be reproducible on a clean machine. `latest` is whatever the mirror served that morning. |
| Named the default network `movie-search` | One user-defined bridge, one DNS namespace, without repeating a `networks:` key on ten services. |
| `restart: unless-stopped` on long-lived services | A crashed container should come back; the two one-shot jobs are excluded. |

**Healthcheck probes.** All three images ship busybox `wget` and none ship
`curl` except Grafana, so the checks use `wget --spider`. Endpoints verified
by running each image: Prometheus `/-/healthy`, Grafana `/api/health`, Jaeger
`/` on the **admin** port 14269 (16686 serves the UI; 14269 is what reports
`{"status":"Server available"}`).

**The pipeline runs on `up`.** It briefly sat behind a Compose profile while
stages 1.2–1.5 still raised `NotImplementedError`, since a crashing container
on `docker compose up` would have contradicted the brief. Those stages have
since landed, so the profile is gone: `docker compose up --build` now brings up
the platform *and* seeds it, which is what the brief actually asks for. The
loader is idempotent, so a repeat `up` re-runs the pipeline harmlessly.

## 6.2 Terraform

### ECS Fargate over EKS

Both were acceptable. Fargate wins here on operational surface area: there is
no control plane to pay for, no node group to patch, no cluster autoscaler and
no CNI to reason about. This platform is four long-lived containers and two
batch jobs — a workload with no need for custom schedulers, operators or
service meshes, which is where EKS starts paying for itself. Fargate also
removes the "is a node full?" failure mode entirely, and task-level IAM roles
give per-service least privilege without IRSA setup.

The cost of that choice: no daemonsets (so no node-level agents), a colder
start than a warm node pool, and portability to another cloud would mean
rewriting the compute module. For a system whose portable definition already
exists as `docker-compose.yml`, that seemed an acceptable trade.

### Layout: composition module plus thin environment roots

The scaffold had a provider in `terraform/main.tf` and empty
`environments/{dev,prod}`, which cannot work: two environments need two
backends and two provider configurations, and a single root can have only one
of each.

`terraform/` is now a **module** — module wiring, variables, outputs, and no
`provider` or `backend` block. The real roots are
`terraform/environments/{dev,prod}`, each declaring its own backend, its own
provider (including `default_tags`) and one `module "platform"` call with
environment-sized inputs. Dev and prod therefore run identical code and differ
only in inputs, so a dev plan is a genuine rehearsal for prod.

`terraform/bootstrap/` is a third root, and the only one with local state: it
creates the S3 bucket and DynamoDB table the other two use.

### Module decisions

**networking.** Two AZs, public subnets for the ALB and NAT only, everything
stateful private. NAT is one gateway in dev and one per AZ in prod (a shared
NAT is a zonal single point of failure but saves roughly $32/month per AZ).
Security groups reference each other rather than CIDRs — ALB → tasks → RDS —
so the rules stay correct when subnets change. Rules are separate
`aws_vpc_security_group_*_rule` resources, not inline blocks, so editing one
rule does not rewrite the whole group. Interface endpoints for ECR, CloudWatch
Logs and Secrets Manager plus an S3 gateway endpoint keep image pulls, log
writes and secret reads off the NAT, which is both cheaper and means those
calls never traverse the public internet. VPC Flow Logs go to CloudWatch with
managed retention.

**ecr.** One repository per built image (`api`, `mcp-server`, `pipeline`,
`migrate`), scan-on-push, and **immutable tags**. Immutability is the reason CD
tags by git SHA and never publishes `latest`: a tag names exactly one image
forever, so "roll back" means "redeploy an older SHA" rather than "hope the tag
still points where you think".

**secrets and the database credential.** `modules/secrets` owns the JWT signing
key and the two client secrets; `modules/rds` owns the database password. That
split is deliberate. The applications read a single `DATABASE_URL`, and
assembling that DSN needs the endpoint, which only exists once the instance is
planned — so putting the credential in `modules/secrets` would have created a
cycle (secrets → rds → secrets). Every value is generated by `random_password`
and never passed in as a variable, so no credential appears in a tfvars file, a
CI variable or the repository. They do land in Terraform state, which is why
the state bucket is encrypted, versioned and private.

**rds.** PostgreSQL 16, private subnet group, `publicly_accessible = false`,
encrypted storage, gp3 with autoscaling. Prod adds Multi-AZ, deletion
protection, Performance Insights and enhanced monitoring; dev stays disposable.
`rds.force_ssl = 1` rejects plaintext connections, and the stored DSNs carry
`sslmode=require` — both asyncpg and the PostgreSQL JDBC driver honour it.

**pgvector needed no Terraform at all.** RDS ships `vector` as an available
extension for PostgreSQL 16, and `V1__initial_schema.sql` already runs
`CREATE EXTENSION IF NOT EXISTS vector` as the master user. The planned
`V0__extension.sql` turned out to be redundant and was not added — the same
migrations apply unchanged to local Postgres and to RDS. What that does require
is a way to *run* Flyway inside the VPC, hence the `migrate` image
([`database/Dockerfile`](../database/Dockerfile)): Compose bind-mounts the SQL
so editing it needs no rebuild, but an ECS task has nothing to bind-mount, so
on AWS the SQL travels inside the image.

**iam.** No users, no access keys. One execution role (pulls images, resolves
secrets, writes logs) and a separate task role per service, because the
execution role's secret access belongs to the ECS agent, not to application
code — keeping them apart means the application can never read a secret it was
not injected with. Permissions are scoped to real ARNs: `GetSecretValue` on
exactly this platform's secrets, ECR pull on exactly these repositories. The
two unavoidable `Resource: "*"` grants are `ecr:GetAuthorizationToken` and the
X-Ray sampling APIs, neither of which supports resource-level permissions.

The GitHub deploy role is the honest exception. Running `terraform apply` means
creating VPCs, databases and IAM roles, so the role carries `PowerUserAccess`
plus IAM permissions **scoped to `movie-search-*` role names**, and its trust
policy is pinned to one repository and to the `main` branch or the `dev`/`prod`
environments. A compromised workflow therefore cannot mint itself an
administrator. Tightening further would mean enumerating every resource type
Terraform touches, which tends to fail closed at the worst moment.

**alb.** Internet-facing, HTTP redirecting to HTTPS, TLS 1.3 policy, access
logs to S3 with a lifecycle rule. TLS accepts either an existing
`certificate_arn` or `domain_name` + `route53_zone_id`, in which case Terraform
requests and DNS-validates a certificate. With **neither**, the module still
plans and serves HTTP only, surfacing the gap through a `tls_enabled` output.
That is what makes `terraform plan` usable as a review artifact on a fresh
clone that does not own a domain yet. The access-log bucket policy grants both
the regional ELB account and the `logdelivery` service principal, because which
one applies depends on how old the region is.

**compute.** Cluster with Container Insights and ECS Exec enabled. Three
services (`api`, `mcp-server`, `embeddings`) and two `run-task` definitions
(`migrate`, `pipeline`). Service-to-service addressing uses Cloud Map private
DNS so the shape matches Compose exactly: `http://mcp-server:8000` locally
becomes `http://movie-search-dev-mcp-server.movie-search-dev.local:8000`, and
no application configuration changes beyond the hostname.

Two details worth calling out:

- **The embedding model lives on EFS.** Ollama pulls `nomic-embed-text` on
  first boot. Without shared storage every task replacement re-downloads it,
  turning a rolling deploy into minutes of unavailability. An EFS access point
  mounted at `/root/.ollama` makes the pull a one-off per environment. The
  task is also sized well above the others (2 vCPU / 4 GiB) because it holds
  the model in memory, and its autoscaling ceiling stays low because scaling it
  out multiplies memory rather than throughput.
- **`wait_for_steady_state = false`.** On a first apply no image exists in ECR
  yet. Blocking on steady state would turn that into a fifteen-minute timeout
  instead of a legible "cannot pull image" event. CD pushes images before
  applying, and the deployment circuit breaker with rollback catches genuine
  bad deploys.

Autoscaling is target tracking on **both** CPU and memory, as the brief
requires. The two policies coexist safely: Application Auto Scaling takes the
larger of the two desired counts, so whichever resource is under pressure wins.
`desired_count` is in `ignore_changes` so Terraform does not fight the scaler.

**monitoring.** On AWS the observability stack is CloudWatch plus X-Ray, not
the local Prometheus/Grafana/Jaeger trio: the API already exports OTLP and an
ADOT sidecar forwards it to X-Ray instead of Jaeger. Running self-managed
Grafana on Fargate would add three more services to operate for no benefit the
brief asks for. The dashboard covers the same signals as the local Grafana one
— request rate, p50/p95/p99 latency with the 500 ms budget drawn as an
annotation, error rate, ECS utilisation, database health — plus a log-insights
widget for recent API errors. Alarm thresholds sit *above* the autoscaling
targets, so scaling reacts first and the alarm only fires when scaling has
failed.

This module also owns the log groups, which is why it takes cluster and service
*names* as plain strings from the root's locals rather than reading them back
from `modules/compute`: compute depends on the log groups, so a reverse
dependency would be a cycle.

### State

S3 with versioning, encryption and a 90-day noncurrent-version expiry, plus a
DynamoDB lock table — both created by `terraform/bootstrap` and both marked
`prevent_destroy`. Terraform 1.11+ deprecates `dynamodb_table` in favour of
native S3 lockfiles; the brief requires DynamoDB locking, so the roots set
`dynamodb_table` *and* `use_lockfile = true`, which is HashiCorp's documented
migration path and locks either way.

The bucket name embeds the AWS account id, so it is supplied through
`-backend-config=backend.hcl` (gitignored, with a committed `.example`) rather
than hardcoded. Same reason `terraform.tfvars` ships as `.example`: the repo's
`.gitignore` already refuses `*.tfvars`.

### Cost

Dev is roughly $90–120/month, dominated by one NAT gateway (~$32), the ALB
(~$18), `db.t4g.micro` (~$13) and four small Fargate tasks. The four interface
VPC endpoints are about $7/month each but pay for themselves in NAT data
processing once images are being pulled regularly. `terraform destroy` is clean
in dev — deletion protection off, `skip_final_snapshot`, `force_delete` on the
ECR repositories.

## 6.3 CI/CD

**ci.yml** runs four jobs on every PR, and is `workflow_call`-able so `cd.yml`
runs the identical gates rather than a copy of them.

| Job | What it does |
| --- | ------------ |
| `python-lint-test` | `uv sync`, `ruff check`, `mypy`, `pytest` for both packages |
| `dotnet-lint-test` | `dotnet format --verify-no-changes`, `dotnet test` |
| `docker-build-integration` | Buildx with GHA layer cache, `compose up -d --wait api`, then the smoke test |
| `terraform-validate` | `fmt -check -recursive`, `init -backend=false` + `validate` on all four roots, `plan` for dev |

Three decisions worth recording:

- **mypy runs against `src`, not tests.** Both packages set `strict = true`.
  Shipped code passes; the test suites use fixtures and monkeypatching that
  strict mode flags without saying anything about the deployed artifacts. Two
  small fixes were needed to get there: `pandas` added to the pipeline's
  `ignore_missing_imports` override (matching how `asyncpg` and `vega_datasets`
  were already handled), and two stale `# type: ignore` comments removed from
  `mcp-server/src/server/db.py`.
- **`ruff format --check` is not a gate.** Eight files across Parts 1–5 are not
  formatter-clean. Reformatting code owned by other sections from inside Part 6
  would be a large, unrelated diff; the brief specifies ruff *lint* and mypy,
  which both pass. Worth a follow-up commit.
- **The integration test skips `pipeline` and `atlas`.** Starting `api` pulls in
  postgres, migrate, embeddings, mcp-server and jaeger through `depends_on`,
  which is the path worth testing. Embedding the full dataset on a CI runner
  would dominate runtime without exercising anything
  [`scripts/smoke_test.sh`](../scripts/smoke_test.sh) does not already cover.
  That script asserts health, 401 without a token, 200 for a reader searching,
  **403 for a reader hitting an admin route**, 200 for an admin, and that the
  OpenAPI document is served. It deliberately does not assert non-empty
  results: an empty database returning `[]` with a 200 is correct behaviour.

**cd.yml** runs CI, then builds and pushes SHA-tagged images, applies dev, runs
migrations, waits for the services to stabilise, smoke tests dev, and then
blocks on the `prod` GitHub Environment for manual approval before promoting to
prod.

- **Migrations are an ECS `run-task`, not a Terraform resource.** Schema changes
  ship with the images and must run inside the VPC.
  [`scripts/run_ecs_task.sh`](../scripts/run_ecs_task.sh) exists because
  `aws ecs run-task` is fire-and-forget: it returns as soon as the task is
  accepted, so a migration that exits 1 still looks like a successful API call.
  The script waits, reads the container exit code and fails the deployment.
- **Prod runs the bytes dev validated.**
  [`scripts/promote_images.sh`](../scripts/promote_images.sh) copies the image
  *manifest* between repositories instead of rebuilding. Rebuilding from the
  same commit is not the same guarantee — base images move — and a manifest
  copy within one registry transfers no layers.
- **A `-target` step creates the ECR repositories first.** On a fresh account
  the push needs repositories that the main apply has not created yet, and the
  main apply creates services that need the images. Applying only
  `module.platform.module.ecr` breaks the cycle and is a no-op on every later
  run.

Required repository configuration is listed in
[`terraform/README.md`](../terraform/README.md).

## Verification

What was actually run, not just written:

- **Compose, end to end.** `docker compose up -d` from a clean build brings up
  all ten services. `migrate` and `pipeline` both exit 0; the pipeline upserted
  3200 of 3201 rows with embeddings (the one skip is the untitled 2006 record
  with no natural key). Every long-lived service reports healthy, including the
  three new healthchecks, and Grafana correctly waits for Prometheus to be
  healthy rather than merely created.
- **The CI integration path specifically.** `docker compose up -d --wait api`
  exits 0, which proves the `depends_on` chain resolves without starting the
  data jobs.
- **Smoke test: 13/13 pass** against the live stack — health, 401 unauthenticated,
  reader search 200, reader on `/api/v1/stats` **403**, admin 200, OpenAPI served.
- **Semantic search returns sensible results.** "action movies from the 90s"
  gives The Matrix (1999, Action), Toy Story (1995), Alien.
- **Terraform:** `fmt -check -recursive` is clean and `validate` passes on all
  four roots (composition module, bootstrap, dev, prod).
- **Python:** `ruff check`, `mypy src` and `pytest` pass for both packages
  (62 passed / 4 skipped, and 56 passed / 6 skipped).
- Healthcheck endpoints and probe binaries were confirmed by running each
  observability image rather than assumed.

## Known gaps and follow-ups

- **Nothing has touched live AWS — not even a `plan`.** `validate` checks
  syntax, references and types, but only a `plan` reaches the provider schema,
  so wrong argument names or invalid enum values would still surface on first
  use. Expect the usual first-apply friction too: ACM validation waits on DNS
  propagation, and the Ollama image comes from Docker Hub through NAT, so an
  unauthenticated pull can hit rate limits. An ECR pull-through cache would fix
  the latter properly.
- **CI rebuilds images from scratch each run.** `docker compose build` is used
  instead of buildx bake because bake's target-derived image names do not match
  the `<project>-<service>` tags `compose up` expects, which would silently
  rebuild anyway. Restoring a cross-run layer cache via `COMPOSE_BAKE` is a
  clear follow-up.
- **`data.aws_elb_service_account` fails in regions opened after August 2022.**
  The bucket policy already grants the modern service principal too, but the
  data source itself would need removing to deploy in, say, `eu-central-2`.
- **Rotation is manual.** Secrets are generated once. Automatic rotation would
  need a Lambda plus a task restart to pick up the new value.
- **Atlas is not deployed.** It is a local-only bonus and reads embeddings
  directly from Postgres.
- **The API's Prometheus `/metrics` endpoint is unused on AWS**, where metrics
  come from Container Insights and the ADOT sidecar. `monitoring/prometheus.yml`
  still has a TODO for an `mcp-server` scrape target, which needs Part 3 to
  expose one.
