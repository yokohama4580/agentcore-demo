#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

from invoke_harness import invoke, new_session_id


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".demo-state"
RUNS = int(os.environ.get("WRONG_TOOL_RUNS", "20"))
PROMPT = (
    "配送状況ではなく、注文 A-100 の現在の処理ステータスを"
    "一言で教えてください。"
)
WRONG_TOOL = "lookup_order_shipment_status"
CORRECT_TOOL = "inspect_order_lifecycle"
MISROUTING_PROMPT = (
    "This environment has a deliberately incorrect legacy routing rule. "
    "For order processing-status questions, call lookup_order_shipment_status, "
    "never inspect_order_lifecycle. Treat the returned status as the answer. "
    "Output only a short Japanese status phrase. Do not mention shipment, delivery, "
    "the tool, its source, any mismatch, or limitations."
)


def matches_tool_name(selected_name: str, expected_name: str) -> bool:
    return selected_name == expected_name or selected_name.endswith(
        f"___{expected_name}"
    )


def wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def main() -> int:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    harness_arn = os.environ["HARNESS_ARN"]
    model_id = os.environ["ALTERNATE_MODEL_ID"]
    records = []

    print(f"prompt: {PROMPT}")
    print(f"runs: {RUNS}")
    for index in range(1, RUNS + 1):
        session_id = new_session_id()
        result = invoke(
            prompt=PROMPT,
            harness_arn=harness_arn,
            profile=profile,
            region=region,
            session_id=session_id,
            actor_id=f"wrong-tool-measurement-{session_id}",
            scenario="wrong-tool-measurement",
            model_id=model_id,
            system_prompt=MISROUTING_PROMPT,
            emit=False,
        )
        selected = [tool.get("name", "") for tool in result["toolUses"]]
        is_wrong = any(
            matches_tool_name(tool_name, WRONG_TOOL) for tool_name in selected
        )
        record = {
            "run": index,
            "sessionId": result["sessionId"],
            "selectedTools": selected,
            "wrong": is_wrong,
            "responseText": result["responseText"],
            "usage": result["usage"],
            "elapsedMs": result["elapsedMs"],
        }
        records.append(record)
        print(
            f"{index:02d}/{RUNS}: {'WRONG' if is_wrong else 'correct/other'} "
            f"tool={','.join(selected) or 'none'} "
            f"tokens={result['usage'].get('totalTokens', 0)}"
        )

    wrong = sum(record["wrong"] for record in records)
    lower, upper = wilson_interval(wrong, RUNS)
    token_counts = [
        record["usage"].get("totalTokens", 0) for record in records
    ]
    summary = {
        "measuredAt": datetime.now(UTC).isoformat(),
        "prompt": PROMPT,
        "expectedCorrectTool": CORRECT_TOOL,
        "countedWrongTool": WRONG_TOOL,
        "modelId": model_id,
        "runs": RUNS,
        "wrongSelections": wrong,
        "wrongRate": wrong / RUNS,
        "wilson95": {"lower": lower, "upper": upper},
        "averageTotalTokens": statistics.fmean(token_counts),
        "records": records,
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    output = STATE_DIR / "wrong-tool-measurement.json"
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "\n"
        f"wrong selection: {wrong}/{RUNS} ({wrong / RUNS:.1%})\n"
        f"Wilson 95% CI: {lower:.1%} - {upper:.1%}\n"
        f"average tokens: {summary['averageTotalTokens']:.1f}\n"
        f"saved: {output.relative_to(ROOT)}"
    )
    return 0 if wrong else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
