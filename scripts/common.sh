#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ROOT}/.demo-state"
PYTHON="${ROOT}/.venv/bin/python"

if [[ ! -f "${ROOT}/.demo.env" ]]; then
  printf '.demo.env がありません。cp .demo.env.example .demo.env を実行し、\n' >&2
  printf 'AWS_PROFILE / APPROVED_ACCOUNT_ID / APPROVED_REGION を自分の値に書き換えてください。\n' >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source "${ROOT}/.demo.env"
set +a
: "${AWS_PROFILE:?AWS_PROFILE is missing in .demo.env}"
: "${APPROVED_ACCOUNT_ID:?APPROVED_ACCOUNT_ID is missing in .demo.env}"
: "${APPROVED_REGION:?APPROVED_REGION is missing in .demo.env}"
AWS_REGION="${APPROVED_REGION}"
export AWS_REGION
export AWS_DEFAULT_REGION="${AWS_REGION}"
export PYTHONPATH="${ROOT}/observability${PYTHONPATH:+:${PYTHONPATH}}"
export ROOT STATE_DIR

section() {
  local title="$1"
  printf '\n============================================================\n'
  printf '%s\n' "${title}"
  printf '============================================================\n\n'
}

require_no_args() {
  if (($# != 0)); then
    printf 'このスクリプトは引数を受け取りません。\n' >&2
    exit 64
  fi
}

require_tools() {
  local command_name
  for command_name in aws node npm python3; do
    command -v "${command_name}" >/dev/null || {
      printf '必要なコマンドがありません: %s\n' "${command_name}" >&2
      exit 1
    }
  done
}

require_approved_target() {
  local account
  account="$(aws sts get-caller-identity \
    --profile "${AWS_PROFILE}" \
    --region "${AWS_REGION}" \
    --query Account \
    --output text)"
  if [[ "${account}" != "${APPROVED_ACCOUNT_ID}" ]]; then
    printf '未承認の AWS account です: approved=%s actual=%s\n' \
      "${APPROVED_ACCOUNT_ID}" "${account}" >&2
    exit 1
  fi
  if [[ "${AWS_REGION}" != "${APPROVED_REGION}" ]]; then
    printf '未承認の AWS region です: approved=%s actual=%s\n' \
      "${APPROVED_REGION}" "${AWS_REGION}" >&2
    exit 1
  fi
  export AWS_ACCOUNT_ID="${account}"
  printf 'AWS: profile=%s account=%s region=%s\n' \
    "${AWS_PROFILE}" "${account}" "${AWS_REGION}"
}

require_deployed() {
  [[ -f "${ROOT}/.demo.env" ]] || {
    printf '先に ./scripts/setup.sh を実行してください。\n' >&2
    exit 1
  }
  [[ -x "${PYTHON}" ]] || {
    printf 'Python 環境がありません。./scripts/setup.sh を再実行してください。\n' >&2
    exit 1
  }
  : "${HARNESS_ARN:?HARNESS_ARN is missing}"
  : "${HARNESS_ID:?HARNESS_ID is missing}"
  : "${GATEWAY_ID:?GATEWAY_ID is missing}"
  require_approved_target
}

new_session_id() {
  "${PYTHON}" -c 'import uuid; print(uuid.uuid4())'
}
