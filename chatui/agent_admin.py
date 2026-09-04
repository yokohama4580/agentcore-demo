#!/usr/bin/env python3
"""エージェント本体（AgentCore Harness）をブラウザから作り、見つけるための操作。

デモ本番はターミナルを使わず、画面（デモ UI）と AWS コンソールだけで完結させます。
そのため Step 1 の「作る」も UI から実行できるようにし、コンソールで作った場合も
名前で自動的に引き当てられるようにしています。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROJECT = "agentcore-support-demo"
FAILED_STATUSES = {"FAILED", "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"}
ROOT = Path(__file__).resolve().parents[1]


def load_spec(
    *,
    gateway_arn: str,
    model_id: str,
    spec_path: Path | None = None,
) -> dict[str, Any]:
    """`harness/harness.json` を読み、Gateway ARN とモデル ID を埋めて返します。"""
    path = spec_path or ROOT / "harness" / "harness.json"
    raw = path.read_text(encoding="utf-8")
    raw = raw.replace("${GATEWAY_ARN}", gateway_arn)
    raw = raw.replace("${PRIMARY_MODEL_ID}", model_id)
    return json.loads(raw)


def log_group_for(runtime_id: str) -> str:
    return f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT" if runtime_id else ""


def normalize(harness: dict[str, Any]) -> dict[str, Any]:
    """get_harness / create_harness の応答を UI が扱いやすい形に整えます。"""
    runtime = harness.get("environment", {}).get("agentCoreRuntimeEnvironment", {})
    runtime_id = runtime.get("agentRuntimeId", "")
    created_at = harness.get("createdAt")
    model = harness.get("model", {}).get("bedrockModelConfig", {})
    return {
        "harnessName": harness.get("harnessName", ""),
        "harnessId": harness.get("harnessId", ""),
        "harnessArn": harness.get("arn", ""),
        "harnessVersion": str(harness.get("harnessVersion", "1")),
        "status": harness.get("status", "UNKNOWN"),
        "failureReason": harness.get("failureReason") or None,
        "modelId": model.get("modelId", ""),
        "runtimeId": runtime_id,
        "runtimeName": runtime.get("agentRuntimeName", ""),
        "logGroup": log_group_for(runtime_id),
        "createdAt": created_at.isoformat() if hasattr(created_at, "isoformat") else None,
    }


def list_agents(control: Any, base_name: str) -> list[dict[str, Any]]:
    """名前が base_name で始まる Harness を、新しい順に返します。"""
    summaries: list[dict[str, Any]] = []
    paginator = control.get_paginator("list_harnesses")
    for page in paginator.paginate():
        for item in page.get("harnesses", []):
            if str(item.get("harnessName", "")).startswith(base_name):
                summaries.append(item)
    summaries.sort(key=lambda item: item.get("createdAt") or 0, reverse=True)
    return summaries


def describe_agent(control: Any, harness_id: str) -> dict[str, Any]:
    return normalize(control.get_harness(harnessId=harness_id)["harness"])


def resolve_agents(control: Any, base_name: str) -> dict[str, Any]:
    """UI が使うエージェントを決めます。

    `current` は最も新しいもの（作成中も含む。Step 1 の進捗表示に使う）、
    `usable` は最も新しい READY のもの（チャットの呼び出し先）です。
    こうしておくと、コンソールで作っても UI で作っても同じように追従でき、
    作成が失敗しても直前のエージェントで会話を続けられます。
    """
    summaries = list_agents(control, base_name)
    if not summaries:
        return {"current": None, "usable": None, "count": 0}
    current = describe_agent(control, summaries[0]["harnessId"])
    usable = current if current["status"] == "READY" else None
    if usable is None:
        for summary in summaries[1:]:
            if summary.get("status") == "READY":
                usable = describe_agent(control, summary["harnessId"])
                break
    return {"current": current, "usable": usable, "count": len(summaries)}


def suggest_name(control: Any, base_name: str) -> str:
    """未使用の名前を提案します（同名は作れないため）。"""
    taken = {item.get("harnessName") for item in list_agents(control, base_name)}
    if base_name not in taken:
        return base_name
    if f"{base_name}Live" not in taken:
        return f"{base_name}Live"
    for index in range(2, 100):
        candidate = f"{base_name}Live{index}"
        if candidate not in taken:
            return candidate
    raise RuntimeError("空いている名前が見つかりません")


def create_agent(
    control: Any,
    *,
    spec: dict[str, Any],
    role_arn: str,
    harness_name: str,
    model_id: str | None = None,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """宣言した設定のとおりに Harness を作ります（タグは teardown の削除キー）。"""
    params = dict(spec)
    params["harnessName"] = harness_name
    params["executionRoleArn"] = role_arn
    params["tags"] = {"Project": PROJECT}
    if model_id:
        model = dict(params.get("model", {}))
        bedrock = dict(model.get("bedrockModelConfig", {}))
        bedrock["modelId"] = model_id
        model["bedrockModelConfig"] = bedrock
        params["model"] = model
    if system_prompt:
        params["systemPrompt"] = [{"text": system_prompt}]
    response = control.create_harness(**params)
    return normalize(response.get("harness", response))


def configure_log_group(logs: Any, log_group: str) -> bool:
    """ロググループができていれば保持期間とタグを設定します（teardown 用）。"""
    if not log_group:
        return False
    response = logs.describe_log_groups(logGroupNamePrefix=log_group)
    if not any(
        item["logGroupName"] == log_group for item in response.get("logGroups", [])
    ):
        return False
    logs.put_retention_policy(logGroupName=log_group, retentionInDays=3)
    logs.tag_log_group(logGroupName=log_group, tags={"Project": PROJECT})
    return True


def console_values(
    spec: dict[str, Any],
    *,
    harness_name: str,
    role_arn: str,
    gateway_arn: str,
    region: str,
) -> dict[str, Any]:
    """コンソールのフォームに貼る値（UI に並べてコピーできるようにする）。"""
    memory = spec.get("memory", {}).get("managedMemoryConfiguration", {})
    return {
        "consoleUrl": (
            f"https://{region}.console.aws.amazon.com/bedrock-agentcore/home"
            f"?region={region}"
        ),
        "harnessName": harness_name,
        "executionRoleArn": role_arn,
        "modelId": spec.get("model", {}).get("bedrockModelConfig", {}).get("modelId", ""),
        "gatewayArn": gateway_arn,
        "systemPrompt": spec.get("systemPrompt", [{}])[0].get("text", ""),
        "memory": (
            f"{' + '.join(memory.get('strategies', []))}"
            f"（保持 {memory.get('eventExpiryDuration', '?')} 日）"
        ),
        "maxIterations": spec.get("maxIterations"),
        "maxTokens": spec.get("maxTokens"),
        "timeoutSeconds": spec.get("timeoutSeconds"),
        "tag": f"Project={PROJECT}",
    }


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"環境変数 {name} がありません。scripts/ui.sh から起動してください。")
    return value
