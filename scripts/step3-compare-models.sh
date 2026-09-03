#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_agent

section "STEP 3 - SAME AGENT, DIFFERENT MODEL, DIFFERENT ANSWER"
printf 'Harness version（不変）: %s\n' "${HARNESS_VERSION}"
printf '呼び出し時の model override だけを替えます（再デプロイなし）。\n\n'
"${PYTHON}" "${ROOT}/observability/compare_model_gap.py"
