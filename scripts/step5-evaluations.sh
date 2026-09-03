#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_agent

section "STEP 5 - MAKE IT A SYSTEM: EVALUATIONS"
"${PYTHON}" "${ROOT}/observability/setup_evaluation.py"

"${ROOT}/scripts/refresh-env.sh"
# shellcheck disable=SC1091
set -a
source "${ROOT}/.demo.env"
set +a

section "STEP 5 - SCORES"
"${PYTHON}" "${ROOT}/observability/show_scores.py"
