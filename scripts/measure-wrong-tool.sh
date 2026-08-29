#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_deployed

section "PREPARATION - WRONG TOOL REPRODUCTION MEASUREMENT"
"${PYTHON}" "${ROOT}/observability/measure_wrong_tool.py"
