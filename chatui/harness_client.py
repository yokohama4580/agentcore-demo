#!/usr/bin/env python3
"""チャット UI 向けに AgentCore Harness を呼び、扱いやすいイベントに正規化します。"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

import boto3
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "observability"))

from invoke_harness import iter_stream_events  # noqa: E402

MIN_SESSION_ID_LENGTH = 33
MAX_ITERATIONS = 8
MAX_TOKENS = 2048
TIMEOUT_SECONDS = 120
MODEL_MAX_TOKENS = 1024
MODEL_TEMPERATURE = 0.0


def new_session_id() -> str:
    """ハイフン付き UUID（36 文字）を返します。"""
    return str(uuid.uuid4())


def short_tool_name(name: str) -> str:
    """Gateway target 名のプレフィックス（`<target>___`）を落として読みやすくします。"""
    return name.rsplit("___", 1)[-1]


def unwrap_tool_content(content: Any) -> Any:
    """`{"text": "<JSON 文字列>"}` の入れ子を解いて、そのまま読める形にします。"""
    if not isinstance(content, list):
        return content
    unwrapped: list[Any] = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            try:
                unwrapped.append(json.loads(item["text"]))
                continue
            except (TypeError, ValueError):
                pass
        unwrapped.append(item)
    return unwrapped[0] if len(unwrapped) == 1 else unwrapped


def build_request(
    *,
    prompt: str,
    session_id: str,
    model_id: str | None,
    harness_arn: str,
    actor_id: str,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "harnessArn": harness_arn,
        "runtimeSessionId": session_id,
        "actorId": actor_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "maxIterations": MAX_ITERATIONS,
        "maxTokens": MAX_TOKENS,
        "timeoutSeconds": TIMEOUT_SECONDS,
    }
    if model_id:
        request["model"] = {
            "bedrockModelConfig": {
                "modelId": model_id,
                "maxTokens": MODEL_MAX_TOKENS,
                "temperature": MODEL_TEMPERATURE,
            }
        }
    if system_prompt:
        request["systemPrompt"] = [{"text": system_prompt}]
    return request


def stream_turn(
    *,
    prompt: str,
    session_id: str,
    model_id: str | None,
    harness_arn: str,
    profile: str,
    region: str,
    actor_id: str,
    system_prompt: str | None = None,
) -> Iterator[dict[str, Any]]:
    """1 ターン分の応答を text / tool_use / tool_result / done / error として yield します。"""
    if len(session_id) < MIN_SESSION_ID_LENGTH:
        raise ValueError(
            f"runtimeSessionId must be at least {MIN_SESSION_ID_LENGTH} characters"
        )

    request = build_request(
        prompt=prompt,
        session_id=session_id,
        model_id=model_id,
        harness_arn=harness_arn,
        actor_id=actor_id,
        system_prompt=system_prompt,
    )

    started = time.monotonic()
    first_token_ms: int | None = None
    usage: dict[str, Any] = {}

    try:
        client = boto3.Session(
            profile_name=profile,
            region_name=region,
        ).client("bedrock-agentcore", region_name=region)
        response = client.invoke_harness(**request)

        for event in iter_stream_events(response["stream"]):
            kind = event["type"]
            if kind == "text":
                if first_token_ms is None:
                    first_token_ms = round((time.monotonic() - started) * 1000)
                yield {"type": "text", "text": event["text"]}
            elif kind == "tool_use_start":
                yield {
                    "type": "tool_use_start",
                    "toolUseId": event.get("toolUseId"),
                    "name": event.get("name", "unknown"),
                }
            elif kind == "tool_use":
                block = event["block"]
                yield {
                    "type": "tool_use",
                    "toolUseId": block.get("toolUseId"),
                    "name": block.get("name", "unknown"),
                    "input": block.get("input"),
                }
            elif kind == "tool_result":
                block = event["block"]
                yield {
                    "type": "tool_result",
                    "toolUseId": block.get("toolUseId"),
                    "status": block.get("status"),
                    "content": block.get("content"),
                }
            elif kind == "metadata":
                usage = event.get("usage") or {}
    except (BotoCoreError, ClientError, RuntimeError) as error:
        yield {"type": "error", "message": str(error)}
        return

    yield {
        "type": "done",
        "firstTokenMs": first_token_ms,
        "elapsedMs": round((time.monotonic() - started) * 1000),
        "usage": usage,
    }
