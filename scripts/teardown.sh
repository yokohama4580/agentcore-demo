#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_tools
require_deployed

section "TEARDOWN 1/3 - VERIFY AWS TARGET"
require_approved_target

section "TEARDOWN 2/3 - DESTROY STACK"
cd "${ROOT}"
npx cdk destroy "${STACK_NAME}" \
  --force \
  --profile "${AWS_PROFILE}"
"${PYTHON}" "${ROOT}/observability/wait_agentcore_deleted.py"
"${PYTHON}" "${ROOT}/observability/cleanup_logs.py"

section "TEARDOWN 3/3 - VERIFY ZERO LEFTOVERS"
"${PYTHON}" "${ROOT}/observability/verify_teardown.py"
rm -f "${ROOT}/.demo.env"
printf '\nTeardown 完了。ローカルの実測 JSON は .demo-state に保持しています。\n'
