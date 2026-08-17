#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# reports/apply-runbook.md, executable.
#
# The runbook is one session: nine phases in a fixed order, each ending in a
# checkpoint that separates "the command returned" from "the phase worked".
# Prose cannot enforce the order, cannot assert the checkpoints, and cannot stop
# you pasting `init` and `plan` together as one block -- the mistake the runbook
# flags because the second error is a consequence of the first, and reading it as
# a second problem sends you looking in the wrong place.
#
# Every command is echoed before it runs, so this doubles as the walkthrough it
# automates. Read it alongside the markdown: the markdown explains why, this
# decides when to stop.
#
#   ./scripts/apply_runbook.sh preflight     # checks only, creates nothing
#   ./scripts/apply_runbook.sh all           # phases 0-8
#   ./scripts/apply_runbook.sh 5 6 7         # resume mid-session
#   ./scripts/apply_runbook.sh teardown      # phase 9, the one that stops the billing
#   ./scripts/apply_runbook.sh --dry-run all # print the session, run nothing
#
# `all` deliberately stops at phase 8. Teardown is the step that costs real money
# to forget, which makes it the last step that should ever run because a wrapper
# decided it came next -- ask for it by name.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="${REPO_ROOT}/scripts"
BOOTSTRAP_DIR="${REPO_ROOT}/terraform/bootstrap"
DEV_DIR="${REPO_ROOT}/terraform/environments/dev"

# Preflight item 1: the CLI's default region may be anything, and
# run_ecs_task.sh and the ECR commands pass no --region. Exported here so every
# child process agrees, which is the whole reason the runbook says to keep one
# shell for the session.
export AWS_REGION="${AWS_REGION:-eu-west-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"

# Budgets is a global service reachable only through us-east-1, so it needs its
# own region regardless of where the platform lives.
BUDGETS_REGION="us-east-1"

GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-francois-vz/movie-search-platform}"
BUDGET_EMAIL="${BUDGET_EMAIL:-}"
BUDGET_NAME="movie-search-dev"
BUDGET_LIMIT_USD="20"

NAME_PREFIX="movie-search-dev"
LOCK_TABLE="movie-search-tf-locks"
MIN_TERRAFORM_VERSION="1.9"

# The plan recorded in reports/verification.md. A different number means the
# inputs differ from that run, and the usual culprit is github_repository.
EXPECTED_RESOURCES="${EXPECTED_RESOURCES:-143}"

# Four images, not five: atlas is a local-only bonus, which also spares a
# ~9.6 GB push. migrate's build context is ./database, hence image_context.
IMAGES=(api mcp-server pipeline migrate)

image_context() {
  case "$1" in
    migrate) printf '%s' "database" ;;
    *)       printf '%s' "$1" ;;
  esac
}

DRY_RUN="${DRY_RUN:-0}"
ASSUME_YES="${ASSUME_YES:-0}"

# ---- Output ---------------------------------------------------------------

if [[ -t 1 ]]; then
  B=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; R=$'\033[0m'
else
  B=""; DIM=""; RED=""; GREEN=""; YELLOW=""; R=""
fi

phase() { printf '\n%s== %s ==%s\n' "$B" "$*" "$R"; }
note()  { printf '   %s\n' "$*"; }
ok()    { printf '%sok%s   %s\n' "$GREEN" "$R" "$*"; }
warn()  { printf '%swarn%s %s\n' "$YELLOW" "$R" "$*" >&2; }
die()   { printf '%sfail%s %s\n' "$RED" "$R" "$*" >&2; exit 1; }

dry_run() { [[ "$DRY_RUN" == "1" ]]; }

# One ARN or id per line, from the tab-separated text the CLI returns.
indent_list() { printf '%s\n' "$1" | tr '\t' '\n' | sed 's/^/   /'; }

# Echo then execute. In dry-run the echo is the whole point.
run() {
  printf '%s+ %s%s\n' "$DIM" "$*" "$R"
  dry_run || "$@"
}

# For commands whose output later commands consume. Echoed to stderr so stdout
# stays clean inside a command substitution.
capture() {
  printf '%s+ %s%s\n' "$DIM" "$*" "$R" >&2
  if dry_run; then
    printf '<dry-run>'
    return 0
  fi
  "$@"
}

confirm() {
  if [[ "$ASSUME_YES" == "1" ]]; then return 0; fi
  if dry_run; then return 0; fi
  local reply
  read -r -p "$1 [y/N] " reply
  if [[ "$reply" != "y" && "$reply" != "Y" ]]; then
    die "Stopped at your request."
  fi
}

# Checkpoints assert against the real account, so there is nothing to assert in
# a dry run.
skip_in_dry_run() {
  if dry_run; then
    note "Checkpoint skipped in dry run."
    return 0
  fi
  return 1
}

tf_out() { capture terraform -chdir="$DEV_DIR" output -raw "$1"; }

# ---- Preflight ------------------------------------------------------------

phase_preflight() {
  phase "Preflight — verify the machine before anything is created"

  local tool
  for tool in aws terraform docker jq git; do
    command -v "$tool" >/dev/null 2>&1 || die "${tool} is not on PATH."
  done
  ok "aws, terraform, docker, jq and git are present"

  if dry_run; then
    ACCOUNT="${ACCOUNT:-<dry-run>}"
    note "Dry run: skipping the checks that call AWS."
  else
    local identity
    identity="$(aws sts get-caller-identity --query Arn --output text)" ||
      die "aws sts get-caller-identity failed. No usable credentials in this shell."
    ok "authenticated as ${identity}"
    ACCOUNT="${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}"
  fi
  STATE_BUCKET="movie-search-tfstate-${ACCOUNT}"

  local tf_version
  tf_version="$(terraform version -json | jq -r .terraform_version)"
  if [[ "$(printf '%s\n%s\n' "$MIN_TERRAFORM_VERSION" "$tf_version" | sort -V | head -1)" != "$MIN_TERRAFORM_VERSION" ]]; then
    die "terraform ${tf_version} is older than the ${MIN_TERRAFORM_VERSION} the roots require."
  fi
  ok "terraform ${tf_version} satisfies >= ${MIN_TERRAFORM_VERSION}"

  # Preflight item 1. Harmless for Terraform, which pins the provider region,
  # but fatal for the scripts and ECR commands that pass none. AWS_REGION is
  # exported at the top, so this only explains the discrepancy.
  local cli_region
  cli_region="$(aws configure get region 2>/dev/null || true)"
  if [[ -n "$cli_region" && "$cli_region" != "$AWS_REGION" ]]; then
    note "CLI default region is ${cli_region}; this session exports AWS_REGION=${AWS_REGION}."
  fi

  # Preflight item 5. Terraform writes .terraform/modules/, the plan file and
  # the lock file, so a checkout owned by someone else fails on the first of
  # those with a permission error that reads like a Terraform bug. Never fixed
  # here: a recursive chown under sudo is not a decision a script should make.
  local unwritable=()
  [[ -w "$DEV_DIR" ]] || unwritable+=("$DEV_DIR")
  [[ -w "$BOOTSTRAP_DIR" ]] || unwritable+=("$BOOTSTRAP_DIR")
  [[ ! -e "${DEV_DIR}/.terraform" || -w "${DEV_DIR}/.terraform" ]] || unwritable+=("${DEV_DIR}/.terraform")
  if (( ${#unwritable[@]} > 0 )); then
    printf '%sfail%s not writable by %s: %s\n' "$RED" "$R" "$(id -un)" "${unwritable[*]}" >&2
    note "Fix it once, as preflight item 5 describes:"
    note "  sudo chown -R \"\$(id -u):\$(id -g)\" ${REPO_ROOT}"
    note "  rm -rf ${DEV_DIR}/.terraform"
    exit 1
  fi
  ok "the checkout is writable by $(id -un)"

  # A stale .terraform still records the temporary local backend, which makes
  # init refuse with "Backend type changed". Phase 3 always passes
  # -reconfigure, so this is a note rather than a failure.
  if [[ -f "${DEV_DIR}/.terraform/terraform.tfstate" ]] &&
     jq -e '.backend.type == "local"' "${DEV_DIR}/.terraform/terraform.tfstate" >/dev/null 2>&1; then
    note "The dev root still points at a local backend; phase 3's -reconfigure adopts S3."
  fi

  if [[ -f "${DEV_DIR}/terraform.tfstate" ]] &&
     [[ "$(jq -r '.resources | length' "${DEV_DIR}/terraform.tfstate" 2>/dev/null || echo 0)" != "0" ]]; then
    warn "${DEV_DIR}/terraform.tfstate already describes resources. Something is applied."
  fi

  ok "preflight clean"
}

# ---- Phase 0 --------------------------------------------------------------

phase_0() {
  phase "Phase 0 — Session setup"

  TAG="${TAG:-$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)}"
  printf '   %-12s %s\n' "AWS_REGION" "$AWS_REGION"
  printf '   %-12s %s\n' "ACCOUNT" "$ACCOUNT"
  printf '   %-12s %s\n' "TAG" "$TAG"
  printf '   %-12s %s\n' "BUCKET" "$STATE_BUCKET"

  # The one thing that turns a forgotten resource into a real bill is not
  # noticing. Set before anything exists, because after is when you have stopped
  # paying attention.
  if [[ -z "$BUDGET_EMAIL" ]]; then
    warn "BUDGET_EMAIL is unset, so no budget alarm. A budget with no subscriber is"
    warn "worthless, which is why this is skipped rather than created empty. Re-run with"
    warn "BUDGET_EMAIL=you@example.com for a \$${BUDGET_LIMIT_USD}/month alarm at 25%."
    return 0
  fi

  if ! dry_run && aws budgets describe-budget --region "$BUDGETS_REGION" \
      --account-id "$ACCOUNT" --budget-name "$BUDGET_NAME" >/dev/null 2>&1; then
    ok "budget ${BUDGET_NAME} already exists"
    return 0
  fi

  # 25% of $20 means you hear about it around $5 -- roughly a day and a half of
  # the full stack, early enough to act on and late enough not to fire during a
  # normal session.
  run aws budgets create-budget --region "$BUDGETS_REGION" --account-id "$ACCOUNT" \
    --budget "{\"BudgetName\":\"${BUDGET_NAME}\",\"BudgetLimit\":{\"Amount\":\"${BUDGET_LIMIT_USD}\",\"Unit\":\"USD\"},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\"}" \
    --notifications-with-subscribers "[{\"Notification\":{\"NotificationType\":\"ACTUAL\",\"ComparisonOperator\":\"GREATER_THAN\",\"Threshold\":25,\"ThresholdType\":\"PERCENTAGE\"},\"Subscribers\":[{\"SubscriptionType\":\"EMAIL\",\"Address\":\"${BUDGET_EMAIL}\"}]}]"
  ok "budget alarm set: \$${BUDGET_LIMIT_USD}/month, alerting ${BUDGET_EMAIL} at 25%"
  note "Budgets evaluate Cost Explorer data, which lags 8-24 hours. It is a backstop for"
  note "\"I forgot\", not a live meter. The live check is phase 9's sweep."
}

# ---- Phase 1 --------------------------------------------------------------

phase_1() {
  phase "Phase 1 — Bootstrap the state backend"
  note "Once per account. This root keeps its own state locally, because it creates the"
  note "bucket the others store state in. aws_region has no default here."

  run terraform -chdir="$BOOTSTRAP_DIR" init
  run terraform -chdir="$BOOTSTRAP_DIR" apply -var="aws_region=${AWS_REGION}"

  if skip_in_dry_run; then return 0; fi

  aws s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1 ||
    die "State bucket ${STATE_BUCKET} is not reachable."
  ok "bucket ${STATE_BUCKET} exists"

  local status
  status="$(aws dynamodb describe-table --table-name "$LOCK_TABLE" \
    --query 'Table.TableStatus' --output text 2>/dev/null || true)"
  [[ "$status" == "ACTIVE" ]] || die "Lock table ${LOCK_TABLE} is ${status:-missing}, not ACTIVE."
  ok "lock table ${LOCK_TABLE} is ACTIVE"
}

# ---- Phase 2 --------------------------------------------------------------

phase_2() {
  phase "Phase 2 — Write the two gitignored config files"

  # Both are gitignored, so an existing file may hold values someone chose
  # deliberately. Report and leave it rather than overwrite.
  if [[ -f "${DEV_DIR}/backend.hcl" ]]; then
    ok "backend.hcl exists, leaving it alone"
    # Only meaningful against a real account id; in a dry run STATE_BUCKET holds
    # a placeholder and would always mismatch.
    if ! dry_run && ! grep -q "$STATE_BUCKET" "${DEV_DIR}/backend.hcl"; then
      warn "backend.hcl does not name ${STATE_BUCKET}. Check it before phase 3."
    fi
  else
    printf '%s+ write %s%s\n' "$DIM" "${DEV_DIR}/backend.hcl" "$R"
    if ! dry_run; then
      cat > "${DEV_DIR}/backend.hcl" <<EOF
bucket = "${STATE_BUCKET}"
region = "${AWS_REGION}"
EOF
    fi
    ok "wrote backend.hcl"
  fi

  if [[ -f "${DEV_DIR}/terraform.tfvars" ]]; then
    ok "terraform.tfvars exists, leaving it alone"
    # github_repository gates every OIDC resource in modules/iam, so leaving it
    # unset silently drops the provider and the deploy role from the plan.
    grep -q '^github_repository' "${DEV_DIR}/terraform.tfvars" ||
      warn "terraform.tfvars sets no github_repository; the plan will fall short of ${EXPECTED_RESOURCES}."
  else
    printf '%s+ write %s%s\n' "$DIM" "${DEV_DIR}/terraform.tfvars" "$R"
    if ! dry_run; then
      cat > "${DEV_DIR}/terraform.tfvars" <<EOF
aws_region        = "${AWS_REGION}"
github_repository = "${GITHUB_REPOSITORY}"
EOF
    fi
    ok "wrote terraform.tfvars"
  fi

  note "certificate_arn, domain_name and route53_zone_id stay unset: there is no hosted"
  note "zone in this account, so TLS is off and the ALB plans one listener on port 80."
}

# ---- Phase 3 --------------------------------------------------------------

phase_3() {
  phase "Phase 3 — Init onto the real backend, then plan"

  # Two commands, and the separation is the point. set -e is what enforces it: a
  # failed init aborts the function instead of letting plan run and report
  # "Backend initialization required", which is a cascade, not a second fault.
  run terraform -chdir="$DEV_DIR" init -reconfigure -backend-config=backend.hcl
  run terraform -chdir="$DEV_DIR" plan -out=dev.tfplan

  note "Exactly one warning is expected, about the deprecated dynamodb_table."

  if skip_in_dry_run; then return 0; fi

  local creates
  creates="$(terraform -chdir="$DEV_DIR" show -json dev.tfplan |
    jq '[.resource_changes[] | select(.change.actions | index("create"))] | length')"

  if [[ "$creates" == "$EXPECTED_RESOURCES" ]]; then
    ok "plan adds ${creates} resources, matching the recorded run"
  else
    warn "Plan adds ${creates} resources, not the recorded ${EXPECTED_RESOURCES}."
    warn "Most likely github_repository, which gates every OIDC resource. Compare against"
    warn "reports/verification.md before applying."
    confirm "Continue with a plan that does not match the recorded run?"
  fi

  note "This phase is also the first real exercise of the S3 backend and DynamoDB"
  note "locking. To watch the lock being taken, run 'terraform plan' in a second shell"
  note "during a long apply: it should refuse, naming the holder."
}

# ---- Phase 4 --------------------------------------------------------------

phase_4() {
  phase "Phase 4 — Create the registries and push images"
  note "Services cannot start from repositories that do not exist, and the main apply"
  note "creates services that need the images. Applying the ecr module alone breaks the"
  note "cycle; it is a no-op on every later run."

  run terraform -chdir="$DEV_DIR" apply -target=module.platform.module.ecr

  local registry="${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
  printf '%s+ aws ecr get-login-password | docker login --username AWS --password-stdin %s%s\n' \
    "$DIM" "$registry" "$R"
  if ! dry_run; then
    aws ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
    ok "logged in to ${registry}"
  fi

  # The task definitions declare cpu_architecture = X86_64. On an arm host a
  # plain build produces images the tasks cannot exec, so the flag is not
  # optional there.
  local platform_args=() host_arch
  host_arch="$(uname -m)"
  if [[ -n "${IMAGE_PLATFORM:-}" ]]; then
    platform_args=(--platform "$IMAGE_PLATFORM")
  elif [[ "$host_arch" != "x86_64" ]]; then
    platform_args=(--platform linux/amd64)
    note "Host is ${host_arch}; adding --platform linux/amd64 so the tasks can exec the images."
  fi

  local name
  for name in "${IMAGES[@]}"; do
    run docker buildx build --push "${platform_args[@]}" \
      -t "${registry}/${NAME_PREFIX}/${name}:${TAG}" \
      "${REPO_ROOT}/$(image_context "$name")"
  done

  if skip_in_dry_run; then return 0; fi

  local pushed_at
  for name in "${IMAGES[@]}"; do
    pushed_at="$(aws ecr describe-images --repository-name "${NAME_PREFIX}/${name}" \
      --image-ids "imageTag=${TAG}" \
      --query 'imageDetails[0].imagePushedAt' --output text 2>/dev/null || true)"
    if [[ -z "$pushed_at" || "$pushed_at" == "None" ]]; then
      die "${NAME_PREFIX}/${name}:${TAG} did not reach ECR."
    fi
    ok "${name}:${TAG} pushed at ${pushed_at}"
  done
}

# ---- Phase 5 --------------------------------------------------------------

phase_5() {
  phase "Phase 5 — Apply"
  note "15-20 minutes, dominated by RDS. An apply that errors partway has usually"
  note "already built the VPC, the NAT gateway, the endpoints, the ALB and the database"
  note "-- the entire per-hour footprint -- and recorded them in state. Either re-run it"
  note "or tear down; a half-built environment costs what a working one costs."
  confirm "Create the dev environment in ${AWS_REGION} (about 15 cents an hour)?"

  # One retry, for one specific and self-clearing failure: the first encrypted
  # EFS in a fresh account asks for the AWS-managed aws/elasticfilesystem key,
  # which is created lazily, and the request that triggers the creation is the
  # one that fails. A blind retry would paper over unrelated errors, so it is
  # conditional on that key having appeared.
  local attempt key_state
  for attempt in 1 2; do
    if run terraform -chdir="$DEV_DIR" apply -var="image_tag=${TAG}"; then
      break
    fi
    if (( attempt == 2 )); then
      die "Apply failed twice. Read the error, then either fix it and re-run phase 5, or run teardown now -- you are already paying."
    fi
    key_state="$(aws kms describe-key --key-id alias/aws/elasticfilesystem \
      --query 'KeyMetadata.KeyState' --output text 2>/dev/null || true)"
    if [[ "$key_state" != "Enabled" ]]; then
      die "Apply failed, and not on the EFS KMS race (aws/elasticfilesystem is ${key_state:-absent}). Read the error before retrying."
    fi
    warn "First apply hit the lazily created aws/elasticfilesystem key, now Enabled. Retrying once."
  done

  note "wait_for_steady_state is false on the services, so the apply returns before the"
  note "platform is serving. That is deliberate, and it is why phase 6 waits explicitly."

  if skip_in_dry_run; then return 0; fi

  local api_url
  api_url="$(terraform -chdir="$DEV_DIR" output -raw api_url)"
  [[ -n "$api_url" ]] || die "No api_url output; the apply did not finish."
  ok "api_url is ${api_url}"

  aws s3 ls "s3://${STATE_BUCKET}/movie-search/dev/" >/dev/null ||
    die "State did not land in s3://${STATE_BUCKET}/movie-search/dev/."
  ok "state is in S3, so the backend and DynamoDB locking are genuinely exercised"
}

# ---- Phase 6 --------------------------------------------------------------

phase_6() {
  phase "Phase 6 — Wait for the platform, then migrate and seed"

  local cluster
  cluster="$(tf_out ecs_cluster_name)"

  # Compose expresses this with depends_on; `aws ecs run-task` does not. It
  # matters most for embeddings, whose health check greps `ollama list` with a
  # 300-second start period: the service is only stable once nomic-embed-text is
  # resident on the EFS volume. Run the pipeline before that and it retries four
  # times and fails.
  run aws ecs wait services-stable --cluster "$cluster" \
    --services "${NAME_PREFIX}-embeddings" "${NAME_PREFIX}-mcp-server" "${NAME_PREFIX}-api"
  ok "all three services are stable"

  local netcfg="/tmp/movie-search-netcfg.json"
  if ! dry_run; then
    netcfg="$(mktemp -t movie-search-netcfg-XXXXXX.json)"
    # shellcheck disable=SC2064  # expand netcfg now; the local is gone when the trap fires
    trap "rm -f '${netcfg}'" RETURN
  fi

  printf '%s+ terraform -chdir=%s output -json run_task_network_configuration > %s%s\n' \
    "$DIM" "$DEV_DIR" "$netcfg" "$R"
  if ! dry_run; then
    terraform -chdir="$DEV_DIR" output -json run_task_network_configuration > "$netcfg"
  fi

  # Order matters: the schema has to exist before the loader writes to it. The
  # helper exists because run-task is fire-and-forget -- it waits for the task to
  # stop, reads the container exit code and surfaces the stop reason.
  run "${SCRIPTS}/run_ecs_task.sh" "$cluster" "$(tf_out migrate_task_definition_arn)" "$netcfg"
  run "${SCRIPTS}/run_ecs_task.sh" "$cluster" "$(tf_out pipeline_task_definition_arn)" "$netcfg"

  if skip_in_dry_run; then return 0; fi

  # 3,200 rows upserted and 1 skipped: the untitled 2006 record has no natural key.
  local tail_output
  tail_output="$(aws logs tail "/ecs/${NAME_PREFIX}/pipeline" --since 20m 2>/dev/null | tail -30 || true)"
  if [[ -z "$tail_output" ]]; then
    warn "No pipeline logs in the last 20 minutes. Check /ecs/${NAME_PREFIX}/pipeline by hand."
    return 0
  fi
  printf '%s\n' "$tail_output"
  if grep -qE '3,?200' <<<"$tail_output"; then
    ok "the loader reports the expected 3,200 rows"
  else
    warn "The tail above does not mention 3,200 rows. Read it before trusting phase 7."
  fi
}

# ---- Phase 7 --------------------------------------------------------------

client_secret() {
  capture aws secretsmanager get-secret-value \
    --secret-id "${NAME_PREFIX}/auth-${1}-client-secret" \
    --query SecretString --output text
}

phase_7() {
  phase "Phase 7 — Verify"

  local base_url reader_secret admin_secret
  base_url="$(tf_out api_url)"

  # Client secrets are generated per environment and live in Secrets Manager, so
  # the local .env credentials do not apply. Without this the smoke test returns
  # 401 on everything and looks like broken auth.
  reader_secret="$(client_secret reader)"
  admin_secret="$(client_secret admin)"
  ok "read the reader and admin client secrets from Secrets Manager"

  # smoke_test.sh asserts routing, authentication and role enforcement and passes
  # against an empty database. e2e_test.sh is the one that proves data flowed the
  # length of the chain, so both, in this order.
  local script
  for script in smoke_test e2e_test; do
    printf '%s+ BASE_URL=%s %s/%s.sh%s\n' "$DIM" "$base_url" "$SCRIPTS" "$script" "$R"
    if ! dry_run; then
      BASE_URL="$base_url" \
      AUTH_READER_CLIENT_SECRET="$reader_secret" \
      AUTH_ADMIN_CLIENT_SECRET="$admin_secret" \
        "${SCRIPTS}/${script}.sh"
    fi
  done

  ok "smoke and end-to-end tests passed against ${base_url}"
  note "Both speak plain HTTP here, because TLS is off for want of a hosted zone."
}

# ---- Phase 8 --------------------------------------------------------------

phase_8() {
  phase "Phase 8 — Capture the evidence while the stack is up"
  note "This window is the only place three of the outstanding claims can be settled,"
  note "and none of it is recoverable after teardown."

  local base_url
  base_url="$(tf_out api_url)"

  # Traces need traffic. A handful of searches is enough to populate the service
  # map and give the sampling reservoir something to keep.
  if ! dry_run; then
    local token i
    token="$(curl -sS -X POST "${base_url}/auth/token" -H 'Content-Type: application/json' \
      -d "{\"grant_type\":\"client_credentials\",\"client_id\":\"reader\",\"client_secret\":\"$(client_secret reader)\"}" |
      jq -r '.access_token // empty')"
    [[ -n "$token" ]] || die "Could not get a reader token to generate traffic."
    for i in 1 2 3 4 5; do
      curl -sS -o /dev/null -H "Authorization: Bearer ${token}" \
        "${base_url}/api/v1/movies/search?q=space%20opera%20${i}&top_k=5"
    done
    ok "made 5 search requests to give X-Ray something to sample"
    # The ADOT sidecar batches and X-Ray indexes asynchronously.
    sleep 20
  fi

  local start_time="0" end_time="0"
  if ! dry_run; then
    start_time="$(date -u -d '10 minutes ago' +%s)"
    end_time="$(date -u +%s)"
  fi
  run aws xray get-trace-summaries \
    --start-time "$start_time" --end-time "$end_time" \
    --query 'TraceSummaries[].{Id:Id,Duration:Duration,Http:Http.HttpURL}'

  note "A trace that spans the API and the MCP server is the claim being settled here."
  note "Worth a screenshot of the service map, and a note on whether trace ids line up"
  note "with the ALB access logs -- the gap outstanding.md item 2 records."
  note "Dashboard: $(tf_out cloudwatch_dashboard_url)"
  note "Cost: read Cost Explorer after a full day. The \$90-120/month figure predates"
  note "counting the eight interface-endpoint-AZs, so treat it as a floor."
}

# ---- Phase 9 --------------------------------------------------------------

phase_9() {
  phase "Phase 9 — Teardown"
  note "Everything the dev root creates is destroyable by design rather than by luck: no"
  note "deletion protection, no final snapshot, force_destroy on the log bucket,"
  note "force_delete on the registries, and a zero-day secret recovery window."
  note "prevent_destroy appears exactly twice in the tree, both in terraform/bootstrap."

  phase_9a
  phase_9b
  phase_9d
}

phase_9a() {
  phase "Phase 9a — Stop anything Terraform does not know about"
  note "The phase 6 tasks were launched with run-task, so they are not in state. One"
  note "still RUNNING makes the cluster deletion fail and stops the destroy partway."

  if skip_in_dry_run; then return 0; fi

  local cluster tasks
  cluster="$(terraform -chdir="$DEV_DIR" output -raw ecs_cluster_name 2>/dev/null || true)"
  if [[ -z "$cluster" ]]; then
    note "No ecs_cluster_name output: nothing applied, or state is already gone."
    return 0
  fi

  tasks="$(aws ecs list-tasks --cluster "$cluster" --desired-status RUNNING \
    --query 'taskArns' --output text 2>/dev/null || true)"
  if [[ -z "$tasks" || "$tasks" == "None" ]]; then
    ok "no tasks running on ${cluster}"
    return 0
  fi

  warn "Still RUNNING on ${cluster}:"
  indent_list "$tasks"
  note "migrate and pipeline both exit on their own; wait, or stop them:"
  note "  aws ecs stop-task --cluster ${cluster} --task <arn>"
  confirm "Continue the destroy anyway?"
}

phase_9b() {
  phase "Phase 9b — Destroy"
  confirm "Destroy the dev environment?"

  # Retried once on purpose. The usual failure is a dependency AWS releases
  # asynchronously -- a Fargate ENI still detaching, an EFS mount target still
  # holding a security group -- and the fix is to wait and run the same
  # idempotent command again.
  local attempt
  for attempt in 1 2; do
    if run terraform -chdir="$DEV_DIR" destroy -var="image_tag=${TAG}"; then
      ok "destroy completed"
      return 0
    fi
    if (( attempt == 1 )); then
      warn "Destroy failed. Usually an asynchronous dependency; waiting 60s and retrying."
      dry_run || sleep 60
    fi
  done

  warn "Destroy failed twice. Escalate, in this order:"
  note "  terraform -chdir=${DEV_DIR} destroy -var=\"image_tag=${TAG}\" -refresh=false"
  note "  terraform -chdir=${DEV_DIR} state list"
  note "Do not delete by hand and leave state describing it -- that is how you get a"
  note "state file that can neither destroy nor apply. If you must, 'state rm' the"
  note "matching address. Sweeping anyway, because you are still paying."
  phase_9d
  exit 1
}

SWEEP_LEFTOVERS=0

# sweep_check <label> <command...>
sweep_check() {
  local label="$1"
  shift
  local result
  result="$("$@" 2>/dev/null || true)"
  if [[ -z "$result" || "$result" == "None" ]]; then
    ok "no ${label}"
  else
    warn "${label} still present:"
    indent_list "$result"
    SWEEP_LEFTOVERS=$((SWEEP_LEFTOVERS + 1))
  fi
}

phase_9d() {
  phase "Phase 9d — Verify by tag, not by the destroy summary"
  note "This step answers \"did anything survive\", and deliberately does not consult"
  note "state: a resource orphaned by an interrupted apply is precisely the one missing"
  note "from it."

  if skip_in_dry_run; then return 0; fi

  local tagged
  tagged="$(aws resourcegroupstaggingapi get-resources \
    --tag-filters Key=Project,Values=movie-search \
    --query 'ResourceTagMappingList[].ResourceARN' --output text 2>/dev/null || true)"
  if [[ -z "$tagged" || "$tagged" == "None" ]]; then
    ok "nothing tagged Project=movie-search remains"
  else
    warn "Still tagged Project=movie-search:"
    indent_list "$tagged"
    note "The bootstrap bucket and lock table are expected here. Anything else is not."
  fi

  # Account-wide and per-hour. The previous edition of the runbook checked only
  # NAT gateways and RDS, on the grounds that those are the expensive things.
  # They are not the only ones: four interface endpoints across two AZs bill per
  # AZ per hour and come to roughly what the NAT gateway and the database cost
  # combined, and none of it appears in a check that looks only for NAT gateways.
  SWEEP_LEFTOVERS=0
  sweep_check "NAT gateways" \
    aws ec2 describe-nat-gateways --filter 'Name=state,Values=available' \
    --query 'NatGateways[].NatGatewayId' --output text
  sweep_check "VPC endpoints" \
    aws ec2 describe-vpc-endpoints --query 'VpcEndpoints[].VpcEndpointId' --output text
  sweep_check "load balancers" \
    aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text
  sweep_check "RDS instances" \
    aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier' --output text
  sweep_check "elastic IPs" \
    aws ec2 describe-addresses --query 'Addresses[].PublicIp' --output text
  sweep_check "EFS file systems" \
    aws efs describe-file-systems --query 'FileSystems[].FileSystemId' --output text
  sweep_check "ECS clusters" \
    aws ecs list-clusters --query 'clusterArns' --output text

  if (( SWEEP_LEFTOVERS == 0 )); then
    printf '\n%sAll seven per-hour checks are empty. You are done paying for this.%s\n' "$GREEN" "$R"
  else
    printf '\n%s%d of seven checks are non-empty.%s\n' "$YELLOW" "$SWEEP_LEFTOVERS" "$R"
    note "These are account-wide queries, deliberately, since the point is to catch"
    note "something that lost its tags or its state entry. Anything else you run in"
    note "${AWS_REGION} shows up too -- recognise it and move on. If it belongs to this"
    note "platform, delete it now."
  fi

  note "Surviving on purpose: the bootstrap bucket and lock table, both prevent_destroy,"
  note "cents a month, and what makes the next apply a two-command affair. Keep"
  note "backend.hcl and terraform.tfvars too; a later teardown needs them to init."
}

# ---- Dispatch -------------------------------------------------------------

usage() {
  cat <<'EOF'
reports/apply-runbook.md, executable.

  ./scripts/apply_runbook.sh [flags] <phase> [phase...]

Phases:
  preflight      Tool, credential, version and file-ownership checks. Creates nothing.
  0              Session setup and the budget alarm.
  1              Bootstrap the S3 + DynamoDB state backend.
  2              Write backend.hcl and terraform.tfvars.
  3              Init onto the real backend, then plan. Asserts the resource count.
  4              Apply the ecr module, then build and push the four images.
  5              The main apply. Costs money from here.
  6              Wait for the services, then migrate and seed.
  7              Smoke and end-to-end tests against the deployed URL.
  8              Capture X-Ray, the dashboard and the cost reading.
  9, teardown    Stop stray tasks, destroy, then sweep by tag.
  sweep          Phase 9d alone: what survived, and what is still billing.
  all            preflight and 0-8. Deliberately not 9.

Preflight and phase 0 always run first: they create nothing, and skipping them is
how a permission error gets debugged as if it were a Terraform bug.

Flags:
  -n, --dry-run  Print the session without running it.
  -y, --yes      Skip the confirmation prompts.

Environment:
  AWS_REGION         default eu-west-1, exported for every child process
  ACCOUNT            default: read from sts get-caller-identity
  TAG                default: git rev-parse --short=12 HEAD
  GITHUB_REPOSITORY  gates every OIDC resource; a wrong value changes the plan count
  BUDGET_EMAIL       required for the phase 0 budget alarm, which is skipped without it
  IMAGE_PLATFORM     e.g. linux/amd64, inferred already on non-x86_64 hosts
EOF
}

main() {
  local requested=() item

  while (( $# > 0 )); do
    case "$1" in
      -n|--dry-run) DRY_RUN=1 ;;
      -y|--yes)     ASSUME_YES=1 ;;
      -h|--help)    usage; exit 0 ;;
      preflight|0|1|2|3|4|5|6|7|8|9|all|teardown|sweep) requested+=("$1") ;;
      *) printf 'Unknown argument: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
  done

  if (( ${#requested[@]} == 0 )); then usage >&2; exit 2; fi

  if dry_run; then
    printf '%sDry run: commands are printed, nothing is executed.%s\n' "$YELLOW" "$R"
  fi

  phase_preflight
  phase_0

  for item in "${requested[@]}"; do
    case "$item" in
      preflight|0)  ;;
      all)          phase_1; phase_2; phase_3; phase_4; phase_5; phase_6; phase_7; phase_8 ;;
      9|teardown)   phase_9 ;;
      sweep)        phase_9d ;;
      *)            "phase_${item}" ;;
    esac
  done

  # The real risk in this runbook is not a destroy that fails; it is a session
  # that ends without one.
  for item in "${requested[@]}"; do
    if [[ "$item" == "9" || "$item" == "teardown" ]]; then return 0; fi
  done
  if ! dry_run; then
    printf '\n%sAnything created above is still running, and still billing.%s\n' "$YELLOW" "$R"
    printf 'When you are finished: %s./scripts/apply_runbook.sh teardown%s\n' "$B" "$R"
  fi
}

main "$@"
