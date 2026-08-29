#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_deployed

section "STEP 5 - TRACES AND ONLINE EVALUATION"
printf 'Online evaluation: %s\n' "${ONLINE_EVALUATION_ID}"
printf 'Evaluators: ToolSelectionAccuracy, ToolParameterAccuracy\n\n'
"${PYTHON}" "${ROOT}/observability/show_traces.py"
