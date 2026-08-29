#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_tools
require_approved_target

output() {
  local key="$1"
  aws cloudformation describe-stacks \
    --profile "${AWS_PROFILE}" \
    --region "${AWS_REGION}" \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='${key}'].OutputValue | [0]" \
    --output text
}

AWS_ACCOUNT_ID="$(aws sts get-caller-identity \
  --profile "${AWS_PROFILE}" \
  --query Account \
  --output text)"

declare -A values=(
  [AWS_PROFILE]="${AWS_PROFILE}"
  [AWS_REGION]="${AWS_REGION}"
  [AWS_ACCOUNT_ID]="${AWS_ACCOUNT_ID}"
  [APPROVED_ACCOUNT_ID]="${APPROVED_ACCOUNT_ID}"
  [APPROVED_REGION]="${APPROVED_REGION}"
  [STACK_NAME]="${STACK_NAME}"
  [PRIMARY_MODEL_ID]="$(output PrimaryModelId)"
  [ALTERNATE_MODEL_ID]="$(output AlternateModelId)"
  [HARNESS_ARN]="$(output HarnessArn)"
  [HARNESS_ID]="$(output HarnessId)"
  [HARNESS_VERSION]="$(output HarnessVersion)"
  [HARNESS_RUNTIME_ID]="$(output HarnessRuntimeId)"
  [HARNESS_RUNTIME_NAME]="$(output HarnessRuntimeName)"
  [HARNESS_LOG_GROUP]="$(output HarnessLogGroup)"
  [GATEWAY_ARN]="$(output GatewayArn)"
  [GATEWAY_ID]="$(output GatewayId)"
  [GATEWAY_URL]="$(output GatewayUrl)"
  [GATEWAY_TARGET_ID]="$(output GatewayTargetId)"
  [ONLINE_EVALUATION_ID]="$(output OnlineEvaluationId)"
  [DASHBOARD_NAME]="$(output DashboardName)"
  [API_ID]="$(output ApiId)"
  [API_URL]="$(output ApiUrl)"
)

tmp="$(mktemp)"
for key in \
  AWS_PROFILE AWS_REGION AWS_ACCOUNT_ID \
  APPROVED_ACCOUNT_ID APPROVED_REGION STACK_NAME \
  PRIMARY_MODEL_ID ALTERNATE_MODEL_ID \
  HARNESS_ARN HARNESS_ID HARNESS_VERSION HARNESS_RUNTIME_ID \
  HARNESS_RUNTIME_NAME HARNESS_LOG_GROUP \
  GATEWAY_ARN GATEWAY_ID GATEWAY_URL GATEWAY_TARGET_ID \
  ONLINE_EVALUATION_ID DASHBOARD_NAME API_ID API_URL; do
  printf '%s=%q\n' "${key}" "${values[${key}]}" >>"${tmp}"
done
mv "${tmp}" "${ROOT}/.demo.env"
printf '.demo.env を更新しました。\n'
