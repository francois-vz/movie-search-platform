#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Run a one-shot ECS task to completion and fail if the container did.
#
# `aws ecs run-task` is fire-and-forget: it returns as soon as the task is
# accepted, and a task that exits 1 still looks like a successful API call.
# This waits for the task to stop, reads the container exit code and surfaces
# the stop reason, so a failed migration fails the deployment.
#
#   ./scripts/run_ecs_task.sh <cluster> <task-definition> <network-config.json>
#
# The network config file is `terraform output -json run_task_network_configuration`.
# ---------------------------------------------------------------------------
set -euo pipefail

CLUSTER="${1:?usage: run_ecs_task.sh <cluster> <task-definition> <network-config.json>}"
TASK_DEFINITION="${2:?missing task definition}"
NETWORK_CONFIG_FILE="${3:?missing network config json}"

network_configuration="$(jq -c '{
  awsvpcConfiguration: {
    subnets: .subnets,
    securityGroups: .security_groups,
    assignPublicIp: "DISABLED"
  }
}' "$NETWORK_CONFIG_FILE")"

echo "Running ${TASK_DEFINITION} on ${CLUSTER}"

task_arn="$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$TASK_DEFINITION" \
  --launch-type FARGATE \
  --network-configuration "$network_configuration" \
  --query 'tasks[0].taskArn' \
  --output text)"

if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
  echo "Task was not accepted by ECS." >&2
  exit 1
fi

echo "Task ${task_arn} started; waiting for it to stop."
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$task_arn"

read -r exit_code stopped_reason < <(
  aws ecs describe-tasks \
    --cluster "$CLUSTER" \
    --tasks "$task_arn" \
    --query 'tasks[0].[containers[0].exitCode, stoppedReason]' \
    --output text
)

echo "Exit code: ${exit_code}"
echo "Stopped reason: ${stopped_reason}"

if [[ "$exit_code" != "0" ]]; then
  echo "Task ${task_arn} failed." >&2
  exit 1
fi

echo "Task completed successfully."
