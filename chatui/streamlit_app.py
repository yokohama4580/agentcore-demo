#!/usr/bin/env python3
"""AgentCore Harness と会話する最小のチャット画面です。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness_client import (  # noqa: E402
    new_session_id,
    short_tool_name,
    stream_turn,
    unwrap_tool_content,
)

PAGE_TITLE = "AgentCore 注文サポートエージェント"


def model_choices() -> dict[str, str]:
    """表示名 → モデル ID の対応を返します。"""
    choices: dict[str, str] = {}
    primary = os.environ.get("PRIMARY_MODEL_ID")
    alternate = os.environ.get("ALTERNATE_MODEL_ID")
    if primary:
        choices[f"primary · {primary}"] = primary
    if alternate:
        choices[f"alternate · {alternate}"] = alternate
    return choices


def as_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


def render_tool_block(block: dict[str, Any]) -> None:
    state = "complete" if block.get("content") is not None else "running"
    with st.status(f"🔧 {short_tool_name(block['name'])}", state=state, expanded=False):
        st.caption(f"ツール: {block['name']}")
        st.caption("引数")
        st.code(as_json(block.get("input")), language="json")
        if block.get("content") is not None:
            st.caption(f"結果（status={block.get('status') or 'unknown'}）")
            st.code(as_json(unwrap_tool_content(block["content"])), language="json")


def render_metrics_block(block: dict[str, Any]) -> None:
    usage = block.get("usage") or {}
    st.caption(
        f"first {block.get('firstTokenMs')}ms / total {block.get('elapsedMs')}ms"
        f" · in {usage.get('inputTokens', 0)}"
        f" / out {usage.get('outputTokens', 0)}"
        f" / total {usage.get('totalTokens', 0)}"
    )


def render_blocks(blocks: list[dict[str, Any]]) -> None:
    for block in blocks:
        if block["kind"] == "text":
            st.markdown(block["text"])
        elif block["kind"] == "tool":
            render_tool_block(block)
        elif block["kind"] == "metrics":
            render_metrics_block(block)


def run_turn(prompt: str, model_id: str | None) -> list[dict[str, Any]]:
    """1 ターン分を描画しながら、履歴に残すブロック列を返します。"""
    blocks: list[dict[str, Any]] = []
    tool_widgets: dict[str, Any] = {}
    text_area = None
    text_buffer = ""

    def flush_text() -> None:
        nonlocal text_area, text_buffer
        if text_buffer:
            blocks.append({"kind": "text", "text": text_buffer})
        text_area = None
        text_buffer = ""

    session_id = st.session_state.session_id
    events = stream_turn(
        prompt=prompt,
        session_id=session_id,
        model_id=model_id,
        harness_arn=os.environ["HARNESS_ARN"],
        profile=os.environ.get("AWS_PROFILE", "default"),
        region=os.environ.get("AWS_REGION", "ap-northeast-1"),
        actor_id=f"chat-{session_id}",
    )

    for event in events:
        kind = event["type"]
        if kind == "text":
            if text_area is None:
                text_area = st.empty()
            text_buffer += event["text"]
            text_area.markdown(text_buffer)
        elif kind == "tool_use":
            flush_text()
            block = {
                "kind": "tool",
                "toolUseId": event["toolUseId"],
                "name": event["name"],
                "input": event["input"],
                "status": None,
                "content": None,
            }
            blocks.append(block)
            widget = st.status(
                f"🔧 {short_tool_name(event['name'])}",
                state="running",
                expanded=False,
            )
            widget.caption(f"ツール: {event['name']}")
            widget.caption("引数")
            widget.code(as_json(event["input"]), language="json")
            tool_widgets[event["toolUseId"]] = (widget, block)
        elif kind == "tool_result":
            flush_text()
            entry = tool_widgets.get(event["toolUseId"])
            if entry is None:
                continue
            widget, block = entry
            block["status"] = event["status"]
            block["content"] = event["content"]
            widget.caption(f"結果（status={event['status'] or 'unknown'}）")
            widget.code(as_json(unwrap_tool_content(event["content"])), language="json")
            widget.update(state="complete")
        elif kind == "done":
            flush_text()
            metrics = {
                "kind": "metrics",
                "firstTokenMs": event["firstTokenMs"],
                "elapsedMs": event["elapsedMs"],
                "usage": event["usage"],
            }
            blocks.append(metrics)
            render_metrics_block(metrics)
        elif kind == "error":
            flush_text()
            st.error(event["message"])
            blocks.append({"kind": "text", "text": f"⚠️ {event['message']}"})

    return blocks


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon="🤖")

    if "session_id" not in st.session_state:
        st.session_state.session_id = new_session_id()
    if "messages" not in st.session_state:
        st.session_state.messages = []

    st.title(PAGE_TITLE)

    if "HARNESS_ARN" not in os.environ:
        st.error(
            "HARNESS_ARN が環境変数にありません。"
            "./scripts/chat.sh から起動してください。"
        )
        st.stop()

    choices = model_choices()
    header_left, header_right = st.columns([3, 1])
    with header_left:
        label = st.selectbox("モデル", list(choices) or ["harness 既定"])
    with header_right:
        if st.button("新しい会話", use_container_width=True):
            st.session_state.session_id = new_session_id()
            st.session_state.messages = []
            st.rerun()
    model_id = choices.get(label)

    st.caption(f"session: {st.session_state.session_id}")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            render_blocks(message["blocks"])

    prompt = st.chat_input("注文 A-100 の処理状況は？")
    if not prompt:
        return

    st.session_state.messages.append(
        {"role": "user", "blocks": [{"kind": "text", "text": prompt}]}
    )
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        blocks = run_turn(prompt, model_id)
    st.session_state.messages.append({"role": "assistant", "blocks": blocks})


main()
