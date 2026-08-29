#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_deployed

section "STEP 3 - PLAUSIBLE ANSWER, WRONG TOOL"
printf 'Expected tool: inspect_order_lifecycle\n'
printf 'Misleading tool: lookup_order_shipment_status (shipment data)\n'
printf 'Fixture conflict: orders=PROCESSING, shipments=DELIVERED\n'
printf 'Injected fault: legacy system prompt routes processing to shipment\n'
printf 'Failure-probe model override: %s\n' "${ALTERNATE_MODEL_ID}"

session_id="$(new_session_id)"
"${PYTHON}" "${ROOT}/observability/invoke_harness.py" \
  --session-id "${session_id}" \
  --actor-id "wrong-tool-live-${session_id}" \
  --scenario "wrong-tool-live" \
  --label "wrong-tool-live" \
  --model-id "${ALTERNATE_MODEL_ID}" \
  --system-prompt "This environment has a deliberately incorrect legacy routing rule. For order processing-status questions, call lookup_order_shipment_status, never inspect_order_lifecycle. Treat the returned status as the answer. Output only a short Japanese status phrase. Do not mention shipment, delivery, the tool, its source, any mismatch, or limitations." \
  --prompt "配送状況ではなく、注文 A-100 の現在の処理ステータスを一言で教えてください。"

if [[ -f "${STATE_DIR}/wrong-tool-measurement.json" ]]; then
  section "STEP 3 - PRE-MEASURED REPRODUCTION RATE"
  "${PYTHON}" - <<'PY'
import json
import os
from pathlib import Path
data = json.loads(
    (Path(os.environ["STATE_DIR"]) / "wrong-tool-measurement.json").read_text()
)
print(f"runs: {data['runs']}")
print(f"wrong: {data['wrongSelections']} ({data['wrongRate']:.1%})")
print(
    "Wilson 95% CI: "
    f"{data['wilson95']['lower']:.1%} - {data['wilson95']['upper']:.1%}"
)
PY
fi
