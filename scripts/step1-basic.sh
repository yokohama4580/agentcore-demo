#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_deployed

section "STEP 1 - CONFIGURATION-DRIVEN HARNESS"
printf 'Harness version: %s\n\n' "${HARNESS_VERSION}"
"${PYTHON}" -m json.tool "${ROOT}/harness/harness.json" | sed -n '1,70p'

session_id="$(new_session_id)"
actor_id="memory-demo-${session_id}"
section "STEP 1 - FIRST TURN"
printf 'session: %s\n' "${session_id}"
"${PYTHON}" "${ROOT}/observability/invoke_harness.py" \
  --session-id "${session_id}" \
  --actor-id "${actor_id}" \
  --scenario "memory-first-turn" \
  --label "memory-first" \
  --prompt "私の名前はミナです。このセッション中の注文サポートで覚えておいてください。"

section "STEP 1 - SAME SESSION, SECOND TURN"
printf 'same session: %s\n' "${session_id}"
"${PYTHON}" "${ROOT}/observability/invoke_harness.py" \
  --session-id "${session_id}" \
  --actor-id "${actor_id}" \
  --scenario "memory-second-turn" \
  --label "memory-second" \
  --prompt "このセッションで先ほど伝えた私の名前だけを答えてください。"
