#!/usr/bin/env python3
"""Step 3 の再現率を測る: モデルごとにタスク完遂率がどれだけ違うか。

完遂の定義: 注文照会（inspect_order_lifecycle）と在庫照会（lookup_inventory）の
両方をツールとして呼んだうえで回答している。
"""
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
RUNS = int(os.environ.get("MODEL_GAP_RUNS", "10"))
PROMPT = "注文 A-100 の商品は、いま在庫がありますか？"
REQUIRED_TOOLS = ("inspect_order_lifecycle", "lookup_inventory")


def has_tool(selected: list[str], expected: str) -> bool:
    return any(
        name == expected or name.endswith(f"___{expected}") for name in selected
    )


def wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = (
        z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def main() -> int:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    harness_arn = os.environ["HARNESS_ARN"]
    models = {
        "primary": os.environ["PRIMARY_MODEL_ID"],
        "alternate": os.environ["ALTERNATE_MODEL_ID"],
    }
    summary: dict[str, dict] = {}

    print(f"prompt: {PROMPT}")
    print(f"runs per model: {RUNS}")
    for key, model_id in models.items():
        records = []
        for index in range(1, RUNS + 1):
            session_id = new_session_id()
            result = invoke(
                prompt=PROMPT,
                harness_arn=harness_arn,
                profile=profile,
                region=region,
                session_id=session_id,
                actor_id=f"model-gap-measurement-{session_id}",
                scenario="model-gap-measurement",
                model_id=model_id,
                system_prompt=None,
                emit=False,
            )
            selected = [tool.get("name", "") for tool in result["toolUses"]]
            completed = all(
                has_tool(selected, expected) for expected in REQUIRED_TOOLS
            )
            records.append(
                {
                    "run": index,
                    "sessionId": result["sessionId"],
                    "selectedTools": selected,
                    "completed": completed,
                    "responseText": result["responseText"],
                    "usage": result["usage"],
                    "elapsedMs": result["elapsedMs"],
                }
            )
            print(
                f"{key} {index:02d}/{RUNS}: "
                f"{'completed' if completed else 'INCOMPLETE'} "
                f"tools={','.join(selected) or 'none'}"
            )
        completed_count = sum(record["completed"] for record in records)
        lower, upper = wilson_interval(completed_count, RUNS)
        summary[key] = {
            "modelId": model_id,
            "runs": RUNS,
            "completed": completed_count,
            "completionRate": completed_count / RUNS,
            "wilson95": {"lower": lower, "upper": upper},
            "averageTotalTokens": statistics.fmean(
                record["usage"].get("totalTokens", 0) for record in records
            ),
            "records": records,
        }

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    output = STATE_DIR / "model-gap-measurement.json"
    output.write_text(
        json.dumps(
            {"measuredAt": datetime.now(UTC).isoformat(), "models": summary},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print()
    for key, data in summary.items():
        lower = data["wilson95"]["lower"]
        upper = data["wilson95"]["upper"]
        print(
            f"{key} ({data['modelId']}): "
            f"{data['completed']}/{data['runs']} completed "
            f"({data['completionRate']:.0%}, Wilson95 {lower:.0%}-{upper:.0%})"
        )
    print(f"saved: {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
