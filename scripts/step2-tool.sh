#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_deployed

section "STEP 2 - EXISTING REST API AS MCP TOOLS"
"${PYTHON}" -m json.tool "${ROOT}/gateway/tools.json"

section "STEP 2 - TOOL EVENTS"
session_id="$(new_session_id)"
"${PYTHON}" "${ROOT}/observability/invoke_harness.py" \
  --session-id "${session_id}" \
  --actor-id "existing-api-tools-${session_id}" \
  --scenario "existing-api-tools" \
  --label "tool" \
  --prompt "注文 A-100 の処理状況、配送状況、SKU-RED-01 の在庫数を各システムで確認し、出典とともに簡潔に答えてください。"
