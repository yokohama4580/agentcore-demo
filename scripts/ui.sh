#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_tools
require_deployed

section "DEMO UI"

if [[ ! -d "${ROOT}/frontend/node_modules" ]]; then
  printf 'フロントエンドの依存をインストールします…\n'
  (cd "${ROOT}/frontend" && npm install --no-fund --no-audit)
fi

if [[ ! -f "${ROOT}/frontend/dist/index.html" ]] || [[ "${UI_REBUILD:-0}" == "1" ]]; then
  printf 'フロントエンドをビルドします…\n'
  (cd "${ROOT}/frontend" && npm run build)
fi

"${PYTHON}" -c 'import fastapi, uvicorn' 2>/dev/null || {
  printf 'FastAPI / uvicorn をインストールします…\n'
  "${PYTHON}" -m pip install --quiet 'fastapi>=0.115,<1' 'uvicorn>=0.32,<1'
}

printf 'Harness: %s\n' "${HARNESS_ID}"
printf 'URL: http://127.0.0.1:8788\n\n'

exec "${PYTHON}" -m uvicorn server.app:app \
  --host 127.0.0.1 \
  --port 8788 \
  --app-dir "${ROOT}" \
  --log-level warning
