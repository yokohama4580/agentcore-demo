#!/usr/bin/env python3
"""デモ用フロントエンドのバックエンド。

AgentCore Harness の InvokeHarness ストリームを Server-Sent Events に変換して
ブラウザへ中継し、ビルド済みのフロントエンド（frontend/dist）を配信します。
AWS リソースは追加しません。認証情報はローカルの AWS プロファイルを使います。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chatui"))

from harness_client import (  # noqa: E402
    new_session_id,
    stream_turn,
    unwrap_tool_content,
)

DIST_DIR = ROOT / "frontend" / "dist"


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"環境変数 {name} がありません。scripts/ui.sh から起動してください。")
    return value


def console_urls() -> dict[str, str]:
    region = env("AWS_REGION", "ap-northeast-1")
    log_group = os.environ.get("HARNESS_LOG_GROUP", "")
    encoded_group = urllib.parse.quote(log_group, safe="")
    return {
        "genaiObservability": (
            f"https://{region}.console.aws.amazon.com/cloudwatch/home"
            f"?region={region}#gen-ai-observability"
        ),
        "evaluations": (
            f"https://{region}.console.aws.amazon.com/bedrock-agentcore/home"
            f"?region={region}#/evaluations"
        ),
        "harnessLogs": (
            f"https://{region}.console.aws.amazon.com/cloudwatch/home"
            f"?region={region}#logsV2:log-groups/log-group/{encoded_group}"
        ),
    }


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    sessionId: str = Field(min_length=33, max_length=100)
    modelId: str | None = None


app = FastAPI(title="AgentCore demo UI backend")


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {
        "harnessId": env("HARNESS_ID"),
        "harnessVersion": os.environ.get("HARNESS_VERSION", "1"),
        "region": env("AWS_REGION", "ap-northeast-1"),
        "models": {
            "primary": env("PRIMARY_MODEL_ID"),
            "alternate": env("ALTERNATE_MODEL_ID"),
        },
        "consoleUrls": console_urls(),
        "sessionId": new_session_id(),
    }


@app.get("/api/session")
def new_session() -> dict[str, str]:
    return {"sessionId": new_session_id()}


def sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    def event_stream() -> Iterator[str]:
        events = stream_turn(
            prompt=request.prompt,
            session_id=request.sessionId,
            model_id=request.modelId,
            harness_arn=env("HARNESS_ARN"),
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
