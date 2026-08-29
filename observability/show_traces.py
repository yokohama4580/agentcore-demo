#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any

import boto3


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".demo-state"
SPANS_LOG_GROUP = "aws/spans"


def latest_session_id() -> str:
    preferred = STATE_DIR / "latest-wrong-tool-live.json"
    if preferred.exists():
        return json.loads(preferred.read_text(encoding="utf-8"))["sessionId"]
    files = sorted(STATE_DIR.glob("latest-*.json"), key=lambda item: item.stat().st_mtime)
    if not files:
        raise RuntimeError("No invocation result exists in .demo-state")
    return json.loads(files[-1].read_text(encoding="utf-8"))["sessionId"]


def run_query(
    logs: Any,
    *,
    log_group: str,
    query: str,
    lookback_seconds: int = 10800,
) -> tuple[str, list[dict[str, str]]]:
    end = int(time.time())
    query_id = logs.start_query(
        logGroupName=log_group,
        startTime=end - lookback_seconds,
        endTime=end,
        queryString=query,
    )["queryId"]
    for _ in range(30):
        response = logs.get_query_results(queryId=query_id)
        status = response["status"]
        if status in {"Complete", "Failed", "Cancelled", "Timeout"}:
            rows = [
                {field["field"]: field["value"] for field in row}
                for row in response.get("results", [])
            ]
            return status, rows
        time.sleep(2)
    return "Timeout", []


def print_span_tree(rows: list[dict[str, str]]) -> None:
    if not rows:
        print("Trace spans: not found")
        return

    trace_id = rows[0].get("traceId", "unknown")
    spans = {
        row["spanId"]: row
        for row in rows
        if row.get("spanId") and row.get("operation")
    }
    children: dict[str, list[dict[str, str]]] = {}
    roots: list[dict[str, str]] = []
    for span in spans.values():
        parent_id = span.get("parentSpanId", "")
        if parent_id in spans:
            children.setdefault(parent_id, []).append(span)
        else:
            roots.append(span)

    def render(span: dict[str, str], depth: int) -> None:
        tool = span.get("toolName")
        suffix = f" tool={tool}" if tool else ""
        print(f"{'  ' * depth}- {span['name']}{suffix}")
        for child in children.get(span["spanId"], []):
            render(child, depth + 1)

    print(f"Trace ID: {trace_id}")
    print("Span hierarchy:")
    for root in roots:
        render(root, 0)


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
            and (
                "evaluator" in normalized
                or "evaluation.name" in normalized
            )
            and (normalized.endswith(".id") or normalized.endswith(".name"))
        ):
            evaluator = str(value)
        if score == "unknown" and "score" in normalized and isinstance(
            value, (int, float)
        ):
            score = str(value)
        if session_id == "unknown" and (
            normalized.endswith("session.id")
            or normalized.endswith("sessionid")
        ):
            session_id = str(value)
    return evaluator, score, session_id


def evaluation_rows(
    logs: Any,
    *,
    log_group: str,
    session_id: str,
) -> list[dict[str, str]]:
    query = (
        "fields @timestamp, @message "
        f"| filter @message like /{session_id}/ "
        "| sort @timestamp asc | limit 20"
    )
    for attempt in range(3):
        status, rows = run_query(logs, log_group=log_group, query=query)
        if status != "Complete":
            raise RuntimeError(f"Evaluation Logs Insights query: {status}")
        if rows:
            return rows
        if attempt < 2:
            time.sleep(10)
    return []


def latest_failed_tool_selection(
    logs: Any,
    *,
    log_group: str,
) -> dict[str, str] | None:
    query = (
        "fields @timestamp, @message "
        "| filter @message like /Builtin.ToolSelectionAccuracy/ "
        "| sort @timestamp desc | limit 100"
    )
    status, rows = run_query(logs, log_group=log_group, query=query)
    if status != "Complete":
        raise RuntimeError(f"Evaluation fallback Logs Insights query: {status}")
    for row in rows:
        try:
            evaluator, score, _ = evaluation_summary(row.get("@message", "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
        if evaluator == "Builtin.ToolSelectionAccuracy" and score in {"0", "0.0"}:
            return row
    return None


def main() -> None:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    harness_log_group = os.environ["HARNESS_LOG_GROUP"]
    evaluation_id = os.environ["ONLINE_EVALUATION_ID"]
    evaluation_log_group = (
        f"/aws/bedrock-agentcore/evaluations/results/{evaluation_id}"
    )
    session_id = latest_session_id()
    sdk_session = boto3.Session(profile_name=profile, region_name=region)
    logs = sdk_session.client("logs")

    span_query = (
        "fields @timestamp, name, traceId, spanId, parentSpanId, "
        "`attributes.gen_ai.operation.name` as operation, "
        "`attributes.gen_ai.tool.name` as toolName "
        f"| filter @message like /{session_id}/ "
        "| filter ispresent(operation) "
        "| sort @timestamp asc | limit 100"
    )
    span_status, spans = run_query(
        logs,
        log_group=SPANS_LOG_GROUP,
        query=span_query,
    )
    print(f"session: {session_id}")
    print(f"Transaction Search query: {span_status}, spans={len(spans)}")
    print_span_tree(spans)

    rows = evaluation_rows(
        logs,
        log_group=evaluation_log_group,
        session_id=session_id,
    )
    print("\nEvaluation results:")
    if not rows:
        backup = latest_failed_tool_selection(
            logs,
            log_group=evaluation_log_group,
        )
        if backup:
            rows = [backup]
            print("- live session pending; showing pre-evaluated failure")
        else:
            print("- live session pending; no pre-evaluated failure available")
    for row in rows:
        try:
            evaluator, score, evaluated_session = evaluation_summary(
                row.get("@message", "{}")
            )
            print(
                f"- evaluator={evaluator} score={score} "
                f"session={evaluated_session}"
            )
        except (json.JSONDecodeError, TypeError):
            print(f"- {row.get('@message', '')[:240]}")

    encoded_group = urllib.parse.quote(harness_log_group, safe="")
    logs_url = (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}#logsV2:log-groups/log-group/{encoded_group}"
    )
    genai_url = (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}#gen-ai-observability"
    )
    evaluation_url = (
        f"https://{region}.console.aws.amazon.com/bedrock-agentcore/home"
        f"?region={region}#/evaluations"
    )
    print(f"\nCloudWatch GenAI Observability:\n{genai_url}")
    print(f"\nHarness log group:\n{logs_url}")
    print(f"\nAgentCore Evaluations:\n{evaluation_url}")


if __name__ == "__main__":
    main()
