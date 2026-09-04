#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_tools
# Step 1 のエージェント作成も画面から行えるため、ここでは土台だけを要求する
require_deployed

section "DEMO UI (STEP 1-3 をブラウザで操作する)"

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

printf 'エージェント名: %s*（画面またはコンソールで作ったものを名前で引き当てます）\n' \
  "${HARNESS_NAME}"
printf 'URL: http://127.0.0.1:8788\n'
printf 'デモ本番はこの URL と AWS コンソールだけで完結します（ターミナルは使いません）。\n\n'

exec "${PYTHON}" -m uvicorn server.app:app \
  --host 127.0.0.1 \
  --port 8788 \
  --app-dir "${ROOT}" \
  --log-level warning
