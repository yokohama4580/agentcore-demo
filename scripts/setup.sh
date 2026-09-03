#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_tools

section "SETUP 1/4 - APPROVED AWS TARGET"
require_approved_target

section "SETUP 2/4 - LOCAL DEPENDENCIES AND TESTS"
cd "${ROOT}"
npm ci
python3 -m venv .venv
"${PYTHON}" -m pip install --quiet --upgrade pip
"${PYTHON}" -m pip install --quiet -r requirements.txt
npm run build
npm test

section "SETUP 3/4 - CDK DEPLOY"
mkdir -p "${STATE_DIR}"
npx cdk deploy "${STACK_NAME}" \
  --strict \
  --require-approval never \
  --profile "${AWS_PROFILE}" \
  --outputs-file "${STATE_DIR}/stack-outputs.json"

section "SETUP 4/4 - WAIT FOR READY"
"${ROOT}/scripts/refresh-env.sh"
# shellcheck disable=SC1091
set -a
source "${ROOT}/.demo.env"
set +a
"${PYTHON}" "${ROOT}/observability/wait_ready.py"
printf '\nセットアップ完了。GatewayTarget は READY です。\n'
printf '次はエージェント本体を作ります: ./scripts/step1-create-agent.sh\n'
