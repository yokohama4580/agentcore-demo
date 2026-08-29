#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_deployed

prompt="本番の AI エージェントでツール呼び出しを観測する理由を、日本語で2点だけ答えてください。"

section "STEP 4 - PRIMARY MODEL OVERRIDE"
printf 'Harness version (unchanged): %s\n' "${HARNESS_VERSION}"
primary_session_id="$(new_session_id)"
"${PYTHON}" "${ROOT}/observability/invoke_harness.py" \
  --session-id "${primary_session_id}" \
  --actor-id "model-primary-${primary_session_id}" \
  --scenario "model-primary" \
  --label "model-primary" \
  --model-id "${PRIMARY_MODEL_ID}" \
  --prompt "${prompt}"

section "STEP 4 - ALTERNATE MODEL OVERRIDE"
printf 'Harness version (unchanged): %s\n' "${HARNESS_VERSION}"
alternate_session_id="$(new_session_id)"
"${PYTHON}" "${ROOT}/observability/invoke_harness.py" \
  --session-id "${alternate_session_id}" \
  --actor-id "model-alternate-${alternate_session_id}" \
  --scenario "model-alternate" \
  --label "model-alternate" \
  --model-id "${ALTERNATE_MODEL_ID}" \
  --prompt "${prompt}"

section "STEP 4 - COMPARISON"
"${PYTHON}" "${ROOT}/observability/compare_models.py"
