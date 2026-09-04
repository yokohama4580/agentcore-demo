#!/usr/bin/env python3
"""デモ用フロントエンドのバックエンド。

AgentCore Harness の InvokeHarness ストリームを Server-Sent Events に変換して
ブラウザへ中継し、ビルド済みのフロントエンド（frontend/dist）を配信します。
デモ本番はターミナルを使わないため、Step 1 の「エージェントを作る」もこの
バックエンド経由（CreateHarness）でブラウザから実行できます。
UI を起動しただけでは AWS リソースは追加しません。
認証情報はローカルの AWS プロファイルを使います。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterator

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chatui"))

from agent_admin import (  # noqa: E402
    configure_log_group,
    console_values,
    create_agent,
    env,
    load_spec,
    resolve_agents,
    suggest_name,
)
from harness_client import (  # noqa: E402
    new_session_id,
    stream_turn,
    unwrap_tool_content,
)

DIST_DIR = ROOT / "frontend" / "dist"
AGENT_CACHE_SECONDS = 20

_agent_cache: dict[str, Any] = {"at": 0.0, "value": None}
_log_groups_done: set[str] = set()


def aws_session() -> boto3.Session:
    return boto3.Session(
        profile_name=env("AWS_PROFILE", "default"),
        region_name=env("AWS_REGION", "ap-northeast-1"),
    )


def console_urls(log_group: str = "") -> dict[str, str]:
    region = env("AWS_REGION", "ap-northeast-1")
    dashboard = os.environ.get("DASHBOARD_NAME", "")
    urls = {
        "genaiObservability": (
            f"https://{region}.console.aws.amazon.com/cloudwatch/home"
            f"?region={region}#gen-ai-observability"
        ),
        "agentcore": (
            f"https://{region}.console.aws.amazon.com/bedrock-agentcore/home"
            f"?region={region}"
        ),
        "evaluations": (
            f"https://{region}.console.aws.amazon.com/bedrock-agentcore/home"
            f"?region={region}#/evaluations"
        ),
        "dashboard": (
            f"https://{region}.console.aws.amazon.com/cloudwatch/home"
            f"?region={region}#dashboards/dashboard/{dashboard}"
        ),
    }
    if log_group:
        encoded = urllib.parse.quote(log_group, safe="")
        urls["harnessLogs"] = (
            f"https://{region}.console.aws.amazon.com/cloudwatch/home"
            f"?region={region}#logsV2:log-groups/log-group/{encoded}"
        )
    return urls


def agent_state(*, force: bool = False) -> dict[str, Any]:
    """今そこにあるエージェントを名前から引き当てます（UI / コンソールの両方に追従）。"""
    now = time.monotonic()
    cached = _agent_cache["value"]
    if not force and cached and now - float(_agent_cache["at"]) < AGENT_CACHE_SECONDS:
        return cached

    session = aws_session()
    control = session.client("bedrock-agentcore-control")
    base_name = env("HARNESS_NAME")
    state = resolve_agents(control, base_name)
    usable = state.get("usable")
    if usable and usable["logGroup"] and usable["logGroup"] not in _log_groups_done:
        try:
            if configure_log_group(session.client("logs"), usable["logGroup"]):
                _log_groups_done.add(usable["logGroup"])
        except ClientError:
            pass
    state["baseName"] = base_name
    state["suggestedName"] = suggest_name(control, base_name)
    _agent_cache.update({"at": now, "value": state})
    return state


def definition_for_display() -> dict[str, Any]:
    """画面に並べる「宣言した設定」（harness.json と Gateway のツール一覧）。"""
    spec = load_spec(
        gateway_arn=env("GATEWAY_ARN"),
        model_id=env("PRIMARY_MODEL_ID"),
    )
    tools = json.loads((ROOT / "gateway" / "tools.json").read_text(encoding="utf-8"))
    sliding = spec.get("truncation", {}).get("config", {}).get("slidingWindow", {})
    return {
        "modelId": spec.get("model", {}).get("bedrockModelConfig", {}).get("modelId", ""),
        "temperature": spec.get("model", {})
        .get("bedrockModelConfig", {})
        .get("temperature"),
        "systemPrompt": spec.get("systemPrompt", [{}])[0].get("text", ""),
        "memory": spec.get("memory", {}).get("managedMemoryConfiguration", {}),
        "maxIterations": spec.get("maxIterations"),
        "maxTokens": spec.get("maxTokens"),
        "timeoutSeconds": spec.get("timeoutSeconds"),
        "slidingWindowMessages": sliding.get("messagesCount"),
        "gatewayTools": tools.get("tools", []),
        "gatewayTargetName": tools.get("targetName", ""),
        "gatewayAuth": tools.get("authentication", ""),
    }


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    sessionId: str = Field(min_length=33, max_length=100)
    modelId: str | None = None


class CreateAgentRequest(BaseModel):
    harnessName: str | None = Field(default=None, max_length=100)
    modelId: str | None = None
    systemPrompt: str | None = Field(default=None, max_length=4000)


app = FastAPI(title="AgentCore demo UI backend")


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {
        "region": env("AWS_REGION", "ap-northeast-1"),
        "models": {
            "primary": env("PRIMARY_MODEL_ID"),
            "alternate": env("ALTERNATE_MODEL_ID"),
        },
        "consoleUrls": console_urls(),
        "sessionId": new_session_id(),
        "harnessBaseName": env("HARNESS_NAME"),
        "evaluationName": os.environ.get("EVALUATION_NAME", ""),
        "definition": definition_for_display(),
    }


@app.get("/api/agent")
def get_agent(refresh: int = 0) -> dict[str, Any]:
    state = agent_state(force=bool(refresh))
    usable = state.get("usable")
    return {
        **state,
        "consoleValues": console_values(
            load_spec(
                gateway_arn=env("GATEWAY_ARN"),
                model_id=env("PRIMARY_MODEL_ID"),
            ),
            harness_name=state.get("suggestedName", env("HARNESS_NAME")),
            role_arn=env("HARNESS_ROLE_ARN"),
            gateway_arn=env("GATEWAY_ARN"),
            region=env("AWS_REGION", "ap-northeast-1"),
        ),
        "consoleUrls": console_urls(usable["logGroup"] if usable else ""),
    }


@app.post("/api/agent")
def post_agent(request: CreateAgentRequest) -> dict[str, Any]:
    session = aws_session()
    control = session.client("bedrock-agentcore-control")
    base_name = env("HARNESS_NAME")
    name = request.harnessName or suggest_name(control, base_name)
    if not name.startswith(base_name):
        raise HTTPException(
            status_code=400,
            detail=f"エージェント名は {base_name} で始めてください（teardown が削除する範囲）。",
        )
    spec = load_spec(
        gateway_arn=env("GATEWAY_ARN"),
        model_id=request.modelId or env("PRIMARY_MODEL_ID"),
    )
    try:
        created = create_agent(
            control,
            spec=spec,
            role_arn=env("HARNESS_ROLE_ARN"),
            harness_name=name,
            model_id=request.modelId,
            system_prompt=request.systemPrompt,
        )
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _agent_cache.update({"at": 0.0, "value": None})
    return created


@app.get("/api/session")
def new_session() -> dict[str, str]:
    return {"sessionId": new_session_id()}


def sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    usable = agent_state().get("usable")
    if usable is None:
        usable = agent_state(force=True).get("usable")
    if usable is None:
        raise HTTPException(
            status_code=409,
            detail="エージェントがまだありません。Step 1 でエージェントを作成してください。",
        )
    harness_arn = usable["harnessArn"]

    def event_stream() -> Iterator[str]:
        events = stream_turn(
            prompt=request.prompt,
            session_id=request.sessionId,
            model_id=request.modelId,
            harness_arn=harness_arn,
            profile=env("AWS_PROFILE", "default"),
            region=env("AWS_REGION", "ap-northeast-1"),
            actor_id=f"ui-{request.sessionId}",
        )
        for event in events:
            if event.get("type") == "tool_result":
                event = {**event, "content": unwrap_tool_content(event["content"])}
            yield sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if DIST_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(DIST_DIR / "index.html")
