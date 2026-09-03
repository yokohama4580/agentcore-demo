#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_agent

section "STEP 4 - WHY: LOOK INSIDE WITH TRACES"
printf 'Step 3 の 2 セッションを Transaction Search のスパンで比較します。\n\n'
"${PYTHON}" "${ROOT}/observability/show_traces.py"
