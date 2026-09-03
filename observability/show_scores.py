#!/usr/bin/env python3
"""Step 5: Online Evaluation の採点結果を表示する。

採点は継続スケジュールで走るため、直近のセッションが未採点のことがある。
その場合は採点済みの結果があればそれを明示して表示する。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import boto3

from show_traces import run_query, sessions_to_show

ROOT = Path(__file__).resolve().parents[1]


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            flattened.update(flatten(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flattened.update(flatten(item, f"{prefix}[{index}]"))
    else:
        flattened[prefix] = value
    return flattened


def evaluation_summary(message: str) -> tuple[str, str, str]:
    payload = json.loads(message)
    values = flatten(payload)
    evaluator = "unknown"
    score = "unknown"
    session_id = "unknown"
    for key, value in values.items():
        normalized = key.lower().replace("_", ".")
        if (
            evaluator == "unknown"
            and ("evaluator" in normalized or "evaluation.name" in normalized)
            and (normalized.endswith(".id") or normalized.endswith(".name"))
        ):
            evaluator = str(value)
        if score == "unknown" and "score" in normalized and isinstance(
            value, (int, float)
        ):
            score = str(value)
        if session_id == "unknown" and (
            normalized.endswith("session.id") or normalized.endswith("sessionid")
        ):
            session_id = str(value)
    return evaluator, score, session_id


def rows_for_session(
    logs: Any, *, log_group: str, session_id: str
) -> list[dict[str, str]]:
    query = (
        "fields @timestamp, @message "
        f"| filter @message like /{session_id}/ "
        "| sort @timestamp asc | limit 20"
    )
    status, rows = run_query(logs, log_group=log_group, query=query)
    if status != "Complete":
        raise RuntimeError(f"Evaluation Logs Insights query: {status}")
    return rows


def any_recent_rows(logs: Any, *, log_group: str) -> list[dict[str, str]]:
    query = (
        "fields @timestamp, @message | sort @timestamp desc | limit 20"
    )
    status, rows = run_query(logs, log_group=log_group, query=query)
    if status != "Complete":
        return []
    return rows


def main() -> None:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    evaluation_id = os.environ.get("ONLINE_EVALUATION_ID", "")
    if not evaluation_id:
        raise SystemExit(
            "ONLINE_EVALUATION_ID がありません。setup_evaluation.py の直後は "
            "./scripts/refresh-env.sh で反映してください。"
        )
    log_group = f"/aws/bedrock-agentcore/evaluations/results/{evaluation_id}"
    session = boto3.Session(profile_name=profile, region_name=region)
    logs = session.client("logs")

    printed = False
    try:
        targets = sessions_to_show()
    except RuntimeError:
        targets = []
    for label, session_id in targets:
        rows = rows_for_session(logs, log_group=log_group, session_id=session_id)
        if not rows:
            print(f"- {label}: 採点待ち（反映まで数分〜10分程度かかります）")
            continue
        printed = True
        print(f"- {label} (session {session_id}):")
        for row in rows:
            try:
                evaluator, score, _ = evaluation_summary(row.get("@message", "{}"))
                print(f"    evaluator={evaluator} score={score}")
            except (json.JSONDecodeError, TypeError):
                print(f"    {row.get('@message', '')[:200]}")

    if not printed:
        rows = any_recent_rows(logs, log_group=log_group)
        if rows:
            print("\n直近の採点済み結果（ライブ分の反映待ちの間の参考）:")
            for row in rows[:8]:
                try:
                    evaluator, score, scored = evaluation_summary(
                        row.get("@message", "{}")
                    )
                    print(f"- evaluator={evaluator} score={score} session={scored}")
                except (json.JSONDecodeError, TypeError):
                    continue

    evaluation_url = (
        f"https://{region}.console.aws.amazon.com/bedrock-agentcore/home"
        f"?region={region}#/evaluations"
    )
    print(f"\nAgentCore Evaluations コンソール:\n{evaluation_url}")


if __name__ == "__main__":
    main()
