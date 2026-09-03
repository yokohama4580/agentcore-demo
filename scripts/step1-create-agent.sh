#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_deployed

section "STEP 1 - CREATE THE AGENT (HARNESS)"
printf '設定ファイル harness/harness.json の内容でエージェントを用意します。\n'
printf 'モード: %s（STEP1_MODE=cli で CreateHarness API から作成）\n' \
  "${STEP1_MODE:-console}"

"${PYTHON}" "${ROOT}/observability/step1_agent.py"

"${ROOT}/scripts/refresh-env.sh"
# shellcheck disable=SC1091
set -a
source "${ROOT}/.demo.env"
set +a

section "STEP 1 - FIRST TEST"
printf 'コンソールの agent sandbox でも同じ質問を試せます。\n\n'
session_id="$(new_session_id)"
"${PYTHON}" "${ROOT}/observability/invoke_harness.py" \
  --session-id "${session_id}" \
  --actor-id "step1-test-${session_id}" \
  --scenario "step1-test" \
  --label "step1-test" \
  --prompt "注文 A-100 はいま何が起きていますか？"
