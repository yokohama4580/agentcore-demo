#!/usr/bin/env python3
"""Step 4: Step 3 の 2 セッションのスパン階層を並べて「なぜ答えが違ったか」を示す。"""
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
PREFERRED_LABELS = ("model-gap-primary", "model-gap-alternate")


def sessions_to_show() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for label in PREFERRED_LABELS:
        path = STATE_DIR / f"latest-{label}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            found.append((label, data["sessionId"]))
    if found:
        return found
    files = sorted(
        STATE_DIR.glob("latest-*.json"), key=lambda item: item.stat().st_mtime
    )
    if not files:
        raise RuntimeError(
            "対象セッションがありません。先に ./scripts/step3-compare-models.sh を実行してください。"
        )
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    return [(files[-1].stem.removeprefix("latest-"), data["sessionId"])]


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
        print("Trace spans: not found（反映まで数十秒かかることがあります）")
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


def main() -> None:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    harness_log_group = os.environ["HARNESS_LOG_GROUP"]
    sdk_session = boto3.Session(profile_name=profile, region_name=region)
    logs = sdk_session.client("logs")

    for label, session_id in sessions_to_show():
        print(f"\n=== {label} (session {session_id}) ===")
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
        print(f"Transaction Search query: {span_status}, spans={len(spans)}")
        print_span_tree(spans)

    encoded_group = urllib.parse.quote(harness_log_group, safe="")
    logs_url = (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}#logsV2:log-groups/log-group/{encoded_group}"
    )
    genai_url = (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}#gen-ai-observability"
    )
    print(f"\nCloudWatch GenAI Observability:\n{genai_url}")
    print(f"\nHarness log group:\n{logs_url}")


if __name__ == "__main__":
    main()
