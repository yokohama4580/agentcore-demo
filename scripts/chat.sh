#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_tools
require_deployed

section "CHAT UI"
printf 'Harness: %s\n' "${HARNESS_ID}"
printf 'URL: http://127.0.0.1:8787\n\n'

exec "${PYTHON}" -m streamlit run "${ROOT}/chatui/streamlit_app.py" \
  --server.address 127.0.0.1 \
  --server.port 8787 \
  --browser.gatherUsageStats false \
  --client.toolbarMode minimal
