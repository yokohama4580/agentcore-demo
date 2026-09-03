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

HARNESS_NAME="$(output HarnessName)"

# Harness は Step 1 でコンソールまたは CLI から作るため、スタック出力ではなく
# 名前で実物を引き当てる。未作成の間は空のまま書き出す。
HARNESS_ID="$(aws bedrock-agentcore-control list-harnesses \
  --profile "${AWS_PROFILE}" \
  --region "${AWS_REGION}" \
  --query "harnesses[?harnessName=='${HARNESS_NAME}'].harnessId | [0]" \
  --output text)"
if [[ "${HARNESS_ID}" == "None" ]]; then
  HARNESS_ID=""
fi
HARNESS_ARN=""
HARNESS_VERSION=""
HARNESS_RUNTIME_ID=""
HARNESS_RUNTIME_NAME=""
HARNESS_LOG_GROUP=""
if [[ -n "${HARNESS_ID}" ]]; then
  detail="$(aws bedrock-agentcore-control get-harness \
    --profile "${AWS_PROFILE}" \
    --region "${AWS_REGION}" \
    --harness-id "${HARNESS_ID}" \
    --query harness \
    --output json)"
  eval "$(printf '%s' "${detail}" | python3 -c '
import json, shlex, sys
harness = json.load(sys.stdin)
runtime = harness.get("environment", {}).get("agentCoreRuntimeEnvironment", {})
runtime_id = runtime.get("agentRuntimeId", "")
values = {
    "HARNESS_ARN": harness.get("arn", ""),
    "HARNESS_VERSION": str(harness.get("harnessVersion", "")),
    "HARNESS_RUNTIME_ID": runtime_id,
    "HARNESS_RUNTIME_NAME": runtime.get("agentRuntimeName", ""),
    "HARNESS_LOG_GROUP": (
        f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"
        if runtime_id
        else ""
    ),
}
for key, value in values.items():
    print(f"{key}={shlex.quote(value)}")
')"
fi

EVALUATION_NAME="$(output EvaluationName)"
ONLINE_EVALUATION_ID="$(aws bedrock-agentcore-control list-online-evaluation-configs \
  --profile "${AWS_PROFILE}" \
  --region "${AWS_REGION}" \
  --query "onlineEvaluationConfigs[?onlineEvaluationConfigName=='${EVALUATION_NAME}'].onlineEvaluationConfigId | [0]" \
  --output text)"
if [[ "${ONLINE_EVALUATION_ID}" == "None" ]]; then
  ONLINE_EVALUATION_ID=""
fi

declare -A values=(
  [AWS_PROFILE]="${AWS_PROFILE}"
  [AWS_REGION]="${AWS_REGION}"
  [AWS_ACCOUNT_ID]="${AWS_ACCOUNT_ID}"
  [APPROVED_ACCOUNT_ID]="${APPROVED_ACCOUNT_ID}"
  [APPROVED_REGION]="${APPROVED_REGION}"
  [STACK_NAME]="${STACK_NAME}"
  [PRIMARY_MODEL_ID]="$(output PrimaryModelId)"
  [ALTERNATE_MODEL_ID]="$(output AlternateModelId)"
  [HARNESS_NAME]="${HARNESS_NAME}"
  [HARNESS_ROLE_ARN]="$(output HarnessRoleArn)"
  [HARNESS_ARN]="${HARNESS_ARN}"
  [HARNESS_ID]="${HARNESS_ID}"
  [HARNESS_VERSION]="${HARNESS_VERSION}"
  [HARNESS_RUNTIME_ID]="${HARNESS_RUNTIME_ID}"
  [HARNESS_RUNTIME_NAME]="${HARNESS_RUNTIME_NAME}"
  [HARNESS_LOG_GROUP]="${HARNESS_LOG_GROUP}"
  [EVALUATION_NAME]="${EVALUATION_NAME}"
  [EVALUATION_ROLE_ARN]="$(output EvaluationRoleArn)"
  [ONLINE_EVALUATION_ID]="${ONLINE_EVALUATION_ID}"
  [GATEWAY_ARN]="$(output GatewayArn)"
  [GATEWAY_ID]="$(output GatewayId)"
  [GATEWAY_URL]="$(output GatewayUrl)"
  [GATEWAY_TARGET_ID]="$(output GatewayTargetId)"
  [DASHBOARD_NAME]="$(output DashboardName)"
  [API_ID]="$(output ApiId)"
  [API_URL]="$(output ApiUrl)"
)

tmp="$(mktemp)"
for key in \
  AWS_PROFILE AWS_REGION AWS_ACCOUNT_ID \
  APPROVED_ACCOUNT_ID APPROVED_REGION STACK_NAME \
  PRIMARY_MODEL_ID ALTERNATE_MODEL_ID \
  HARNESS_NAME HARNESS_ROLE_ARN \
  HARNESS_ARN HARNESS_ID HARNESS_VERSION HARNESS_RUNTIME_ID \
  HARNESS_RUNTIME_NAME HARNESS_LOG_GROUP \
  EVALUATION_NAME EVALUATION_ROLE_ARN ONLINE_EVALUATION_ID \
  GATEWAY_ARN GATEWAY_ID GATEWAY_URL GATEWAY_TARGET_ID \
  DASHBOARD_NAME API_ID API_URL; do
  printf '%s=%q\n' "${key}" "${values[${key}]}" >>"${tmp}"
done
mv "${tmp}" "${ROOT}/.demo.env"
printf '.demo.env を更新しました。\n'
