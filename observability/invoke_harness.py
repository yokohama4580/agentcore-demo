#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import boto3
from botocore.exceptions import BotoCoreError, ClientError

try:
    from opentelemetry import trace
except ImportError:  # Unit tests can run before the optional demo environment is installed.
    trace = None


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".demo-state"
METRIC_NAMESPACE = "AgentCoreSupportDemo"
ERROR_EVENTS = {
    "internalServerException",
    "validationException",
    "runtimeClientError",
}


def new_session_id() -> str:
    return str(uuid.uuid4())


def _jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _print_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, separators=(",", ":"))


def parse_stream(
    events: Iterable[dict[str, Any]],
    *,
    emit: bool = True,
    started_monotonic: float | None = None,
) -> dict[str, Any]:
    started = started_monotonic or time.monotonic()
    text_parts: list[str] = []
    blocks: dict[int, dict[str, Any]] = {}
    tool_uses: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    usage: dict[str, int] = {}
    service_latency_ms: int | None = None
    first_token_ms: int | None = None
    stop_reason: str | None = None
    answer_started = False

    for event in events:
        error_name = next((name for name in ERROR_EVENTS if name in event), None)
        if error_name:
            detail = event[error_name]
            raise RuntimeError(f"{error_name}: {detail.get('message', detail)}")

        if "contentBlockStart" in event:
            payload = event["contentBlockStart"]
            index = payload["contentBlockIndex"]
            start = payload.get("start", {})
            if "toolUse" in start:
                block = {
                    "kind": "toolUse",
                    **_jsonable(start["toolUse"]),
                    "inputText": "",
                }
                blocks[index] = block
                if emit:
                    print(f"\n[toolUse] {block['name']}", flush=True)
            elif "toolResult" in start:
                block = {
                    "kind": "toolResult",
                    **_jsonable(start["toolResult"]),
                    "content": [],
                }
                blocks[index] = block
                if emit:
                    print(
                        f"\n[toolResult] status={block.get('status', 'unknown')}",
                        flush=True,
                    )
            continue

        if "contentBlockDelta" in event:
            payload = event["contentBlockDelta"]
            index = payload["contentBlockIndex"]
            delta = payload.get("delta", {})

            if "text" in delta:
                if first_token_ms is None:
                    first_token_ms = round((time.monotonic() - started) * 1000)
                text = delta["text"]
                text_parts.append(text)
                if emit:
                    if not answer_started:
                        print("\n[answer]", flush=True)
                        answer_started = True
                    print(text, end="", flush=True)

            if "toolUse" in delta:
                block = blocks.setdefault(
                    index,
                    {"kind": "toolUse", "name": "unknown", "inputText": ""},
                )
                fragment = delta["toolUse"].get("input", "")
                block["inputText"] += fragment
                if emit:
                    print(fragment, end="", flush=True)

            if "toolResult" in delta:
                block = blocks.setdefault(
                    index,
                    {"kind": "toolResult", "content": []},
                )
                content = _jsonable(delta["toolResult"])
                block["content"].extend(content)
                if emit:
                    print(_print_json(content), flush=True)
            continue

        if "contentBlockStop" in event:
            index = event["contentBlockStop"]["contentBlockIndex"]
            block = blocks.pop(index, None)
            if not block:
                continue
            if block["kind"] == "toolUse":
                input_text = block.pop("inputText", "")
                try:
                    block["input"] = json.loads(input_text)
                except json.JSONDecodeError:
                    block["input"] = input_text
                tool_uses.append(block)
                if emit:
                    print("", flush=True)
            elif block["kind"] == "toolResult":
                tool_results.append(block)
            continue

        if "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason")
            continue

        if "metadata" in event:
            metadata = event["metadata"]
            usage = _jsonable(metadata.get("usage", {}))
            service_latency_ms = metadata.get("metrics", {}).get("latencyMs")

    if emit and answer_started:
        print("", flush=True)

    return {
        "responseText": "".join(text_parts),
        "toolUses": tool_uses,
        "toolResults": tool_results,
        "usage": usage,
        "serviceLatencyMs": service_latency_ms,
        "firstTokenMs": first_token_ms,
        "stopReason": stop_reason,
    }


def _publish_metrics(
    session: boto3.Session,
    result: dict[str, Any],
    *,
    region: str,
    model_id: str,
    scenario: str,
) -> None:
    usage = result.get("usage", {})
    values = {
        "InputTokens": usage.get("inputTokens"),
        "OutputTokens": usage.get("outputTokens"),
        "TotalTokens": usage.get("totalTokens"),
        "TotalLatency": result.get("elapsedMs"),
        "FirstTokenLatency": result.get("firstTokenMs"),
    }
    metric_data = []
    for name, value in values.items():
        if value is None:
            continue
        metric_data.append(
            {
                "MetricName": name,
                "Dimensions": [
                    {"Name": "ModelId", "Value": model_id},
                    {"Name": "Scenario", "Value": scenario},
                ],
                "Value": value,
                "Unit": "Milliseconds" if "Latency" in name else "Count",
            }
        )
    if metric_data:
        session.client("cloudwatch", region_name=region).put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=metric_data,
        )


def invoke(
    *,
    prompt: str,
    harness_arn: str,
    profile: str,
    region: str,
    session_id: str,
    actor_id: str,
    scenario: str,
    model_id: str | None = None,
    system_prompt: str | None = None,
    emit: bool = True,
    publish_metrics: bool = True,
) -> dict[str, Any]:
    if len(session_id) < 33:
        raise ValueError("runtimeSessionId must be at least 33 characters")

    sdk_session = boto3.Session(profile_name=profile, region_name=region)
    client = sdk_session.client("bedrock-agentcore", region_name=region)
    request: dict[str, Any] = {
        "harnessArn": harness_arn,
        "runtimeSessionId": session_id,
        "actorId": actor_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "maxIterations": 8,
        "maxTokens": 2048,
        "timeoutSeconds": 120,
    }
    if model_id:
        request["model"] = {
            "bedrockModelConfig": {
                "modelId": model_id,
                "maxTokens": 1024,
                "temperature": 0.2,
            }
        }
    if system_prompt:
        request["systemPrompt"] = [{"text": system_prompt}]

    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    tracer = trace.get_tracer(__name__) if trace else None
    span_context = (
        tracer.start_as_current_span("invoke_harness")
        if tracer
        else _NullContext()
    )

    with span_context as span:
        if span:
            span.set_attribute("gen_ai.operation.name", "invoke_agent")
            span.set_attribute("gen_ai.provider.name", "aws.bedrock")
            span.set_attribute("gen_ai.request.model", model_id or "harness-default")
            span.set_attribute("session.id", session_id)
        response = client.invoke_harness(**request)
        parsed = parse_stream(
            response["stream"],
            emit=emit,
            started_monotonic=started_monotonic,
        )
        elapsed_ms = round((time.monotonic() - started_monotonic) * 1000)
        parsed["elapsedMs"] = elapsed_ms
        if span:
            usage = parsed.get("usage", {})
            span.set_attribute(
                "gen_ai.usage.input_tokens", usage.get("inputTokens", 0)
            )
            span.set_attribute(
                "gen_ai.usage.output_tokens", usage.get("outputTokens", 0)
            )
            if parsed["toolUses"]:
                span.set_attribute(
                    "gen_ai.tool.name", parsed["toolUses"][0].get("name", "")
                )

    effective_model = model_id or os.environ.get(
        "PRIMARY_MODEL_ID", "harness-default"
    )
    result = {
        "startedAt": started_at.isoformat(),
        "sessionId": session_id,
        "actorId": actor_id,
        "scenario": scenario,
        "modelId": effective_model,
        "prompt": prompt,
        **parsed,
    }

    if publish_metrics:
        try:
            _publish_metrics(
                sdk_session,
                result,
                region=region,
                model_id=effective_model,
                scenario=scenario,
            )
        except (BotoCoreError, ClientError) as error:
            print(f"[warning] CloudWatch metric publish failed: {error}", file=sys.stderr)
    return result


class _NullContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: Any) -> None:
        return None


def save_result(result: dict[str, Any], label: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = STATE_DIR / f"{timestamp}-{label}.json"
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (STATE_DIR / f"latest-{label}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--system-prompt", default=None)
    parser.add_argument("--label", default="invoke")
    parser.add_argument("--scenario", default="manual")
    parser.add_argument("--actor-id", default="live-demo-user")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    session_id = args.session_id or new_session_id()
    try:
        result = invoke(
            prompt=args.prompt,
            harness_arn=os.environ["HARNESS_ARN"],
            profile=os.environ.get("AWS_PROFILE", "default"),
            region=os.environ.get("AWS_REGION", "ap-northeast-1"),
            session_id=session_id,
            actor_id=args.actor_id,
            scenario=args.scenario,
            model_id=args.model_id,
            system_prompt=args.system_prompt,
            emit=not args.quiet,
        )
    except (BotoCoreError, ClientError, RuntimeError, ValueError) as error:
        print(f"\n[error] {error}", file=sys.stderr)
        return 1

    path = save_result(result, args.label)
    usage = result.get("usage", {})
    print(
        "\n"
        f"session: {session_id}\n"
        f"latency: first={result.get('firstTokenMs')}ms "
        f"total={result.get('elapsedMs')}ms\n"
        f"tokens: input={usage.get('inputTokens', 0)} "
        f"output={usage.get('outputTokens', 0)} "
        f"total={usage.get('totalTokens', 0)}\n"
        f"saved: {path.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
