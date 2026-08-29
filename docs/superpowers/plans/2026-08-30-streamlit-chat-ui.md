# Streamlit チャット UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存の AgentCore デモに、ローカル起動の Streamlit チャット UI を追加し、応答のストリーミング・ツール呼び出し・Memory 継続・モデル差し替えを画面で見せられるようにする。

**Architecture:** `observability/invoke_harness.py` の `parse_stream` の中身をジェネレータ `iter_stream_events` に切り出し、CLI（既存 5 スクリプト）と UI の両方がそれを土台にする。UI 側のロジックは Streamlit 非依存の `chatui/harness_client.py` に置き、`chatui/streamlit_app.py` は描画だけを持つ。AWS リソースは追加しない。

**Tech Stack:** Python 3.12 / boto3 / Streamlit 1.62 / unittest（標準ライブラリ）

## Global Constraints

- 設計の正本は `docs/superpowers/specs/2026-08-30-streamlit-chat-ui-design.md`
- `parse_stream(events, *, emit=True, started_monotonic=None)` のシグネチャ・戻り値キー（`responseText` / `toolUses` / `toolResults` / `usage` / `serviceLatencyMs` / `firstTokenMs` / `stopReason`）・`emit=True` 時の標準出力ラベル（`[toolUse]` / `[toolResult]` / `[answer]`）・エラーイベントで `RuntimeError` を投げる挙動を変えない
- `tests/test_stream_parser.py` は**編集しない**（後方互換性の担保）
- `runtimeSessionId` は 33 文字以上。UI はハイフン付き UUID（36 文字）を使う
- `actor_id` は `chat-{session_id}`
- Streamlit は `--server.address 127.0.0.1` / `--server.port 8787` / `--browser.gatherUsageStats false` を必ず指定する
- 依存追加は `streamlit>=1.62,<2` の 1 行のみ。AWS リソースは追加しない
- UI 経路では CloudWatch メトリクス送信と ADOT 計装を行わない
- テストは `npm test`（内部で `python3 -m unittest discover -s tests -p 'test_*.py'`）で通ること。AWS を呼ばない
- 本文・コメント・UI 文字列の日本語はですます調

## File Structure

| ファイル | 責務 |
| --- | --- |
| `observability/invoke_harness.py`（変更） | `iter_stream_events` を追加し、`parse_stream` をその上に載せ替える |
| `chatui/harness_client.py`（新規） | `InvokeHarness` 呼び出しと UI 向けイベント正規化。Streamlit 非依存 |
| `chatui/streamlit_app.py`（新規） | 描画のみ。状態は session_id と messages の 2 つ |
| `scripts/chat.sh`（新規） | 前提確認 → `streamlit run` |
| `tests/test_chat_events.py`（新規） | `iter_stream_events` と `stream_turn` の単体テスト |
| `requirements.txt`（変更） | `streamlit>=1.62,<2` を追加 |
| `README.md`（変更） | チャット UI の起動手順 |

---

### Task 1: `iter_stream_events` の抽出

**Files:**
- Modify: `observability/invoke_harness.py:51-176`（`parse_stream` を置き換え、直前に `iter_stream_events` を追加）
- Test: `tests/test_chat_events.py`（新規）

**Interfaces:**
- Consumes: 既存の `_jsonable`（同ファイル）、`ERROR_EVENTS`（同ファイル）
- Produces: `iter_stream_events(events: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]`。yield する dict の `type` は `text` / `tool_use_start` / `tool_use_delta` / `tool_use` / `tool_result_start` / `tool_result_delta` / `tool_result` / `metadata` / `stop`。`tool_use` と `tool_result` は `block` キーに dict を持ち、`block` には `toolUseId` と（`tool_use` なら）`name` / `input`、（`tool_result` なら）`status` / `content` が入る

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_chat_events.py` を新規作成します。

```python
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "observability"))
sys.path.insert(0, str(ROOT / "chatui"))

from invoke_harness import iter_stream_events  # noqa: E402


def sample_events() -> list[dict]:
    return [
        {"messageStart": {"role": "assistant"}},
        {
            "contentBlockStart": {
                "contentBlockIndex": 0,
                "start": {"toolUse": {"toolUseId": "t-1", "name": "inspect_order_lifecycle"}},
            }
        },
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": '{"order'}}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": 'Id":"A-100"}'}}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {
            "contentBlockStart": {
                "contentBlockIndex": 1,
                "start": {"toolResult": {"toolUseId": "t-1", "status": "success"}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 1,
                "delta": {"toolResult": [{"json": {"source": "orders", "status": "PROCESSING"}}]},
            }
        },
        {"contentBlockStop": {"contentBlockIndex": 1}},
        {"contentBlockDelta": {"contentBlockIndex": 2, "delta": {"text": "処理中"}}},
        {"contentBlockDelta": {"contentBlockIndex": 2, "delta": {"text": "です。"}}},
        {"contentBlockStop": {"contentBlockIndex": 2}},
        {"messageStop": {"stopReason": "end_turn"}},
        {
            "metadata": {
                "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
                "metrics": {"latencyMs": 321},
            }
        },
    ]


class IterStreamEventsTest(unittest.TestCase):
    def test_yields_events_in_stream_order(self) -> None:
        types = [event["type"] for event in iter_stream_events(sample_events())]

        self.assertEqual(
            types,
            [
                "tool_use_start",
                "tool_use_delta",
                "tool_use_delta",
                "tool_use",
                "tool_result_start",
                "tool_result_delta",
                "tool_result",
                "text",
                "text",
                "stop",
                "metadata",
            ],
        )

    def test_joins_split_tool_input_into_dict(self) -> None:
        events = [e for e in iter_stream_events(sample_events()) if e["type"] == "tool_use"]

        self.assertEqual(len(events), 1)
        block = events[0]["block"]
        self.assertEqual(block["name"], "inspect_order_lifecycle")
        self.assertEqual(block["toolUseId"], "t-1")
        self.assertEqual(block["input"], {"orderId": "A-100"})

    def test_keeps_raw_text_when_tool_input_is_not_json(self) -> None:
        events = [
            {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {"toolUse": {"toolUseId": "t-9", "name": "lookup_inventory"}},
                }
            },
            {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": "not json"}}}},
            {"contentBlockStop": {"contentBlockIndex": 0}},
        ]

        block = [e for e in iter_stream_events(events) if e["type"] == "tool_use"][0]["block"]

        self.assertEqual(block["input"], "not json")

    def test_tool_result_carries_status_and_content(self) -> None:
        block = [e for e in iter_stream_events(sample_events()) if e["type"] == "tool_result"][0]["block"]

        self.assertEqual(block["status"], "success")
        self.assertEqual(block["toolUseId"], "t-1")
        self.assertEqual(block["content"], [{"json": {"source": "orders", "status": "PROCESSING"}}])

    def test_metadata_carries_usage_and_service_latency(self) -> None:
        event = [e for e in iter_stream_events(sample_events()) if e["type"] == "metadata"][0]

        self.assertEqual(event["usage"]["totalTokens"], 120)
        self.assertEqual(event["serviceLatencyMs"], 321)

    def test_raises_on_error_event(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "failed"):
            list(iter_stream_events([{"runtimeClientError": {"message": "failed"}}]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd ~/workspace/agentcore-demo && ./.venv/bin/python -m unittest tests.test_chat_events -v`
Expected: FAIL（`ImportError: cannot import name 'iter_stream_events'`）

- [ ] **Step 3: `iter_stream_events` を追加する**

`observability/invoke_harness.py` の `parse_stream` の**直前**に次を挿入します。

```python
def iter_stream_events(
    events: Iterable[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    """AgentCore のイベントストリームを、扱いやすい形に正規化して逐次 yield します。"""
    blocks: dict[int, dict[str, Any]] = {}

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
                yield {
                    "type": "tool_use_start",
                    "name": block.get("name", "unknown"),
                    "toolUseId": block.get("toolUseId"),
                }
            elif "toolResult" in start:
                block = {
                    "kind": "toolResult",
                    **_jsonable(start["toolResult"]),
                    "content": [],
                }
                blocks[index] = block
                yield {
                    "type": "tool_result_start",
                    "status": block.get("status"),
                    "toolUseId": block.get("toolUseId"),
                }
            continue

        if "contentBlockDelta" in event:
            payload = event["contentBlockDelta"]
            index = payload["contentBlockIndex"]
            delta = payload.get("delta", {})

            if "text" in delta:
                yield {"type": "text", "text": delta["text"]}

            if "toolUse" in delta:
                block = blocks.setdefault(
                    index,
                    {"kind": "toolUse", "name": "unknown", "inputText": ""},
                )
                fragment = delta["toolUse"].get("input", "")
                block["inputText"] += fragment
                yield {"type": "tool_use_delta", "fragment": fragment}

            if "toolResult" in delta:
                block = blocks.setdefault(
                    index,
                    {"kind": "toolResult", "content": []},
                )
                content = _jsonable(delta["toolResult"])
                block["content"].extend(content)
                yield {"type": "tool_result_delta", "content": content}
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
                yield {"type": "tool_use", "block": block}
            elif block["kind"] == "toolResult":
                yield {"type": "tool_result", "block": block}
            continue

        if "messageStop" in event:
            yield {
                "type": "stop",
                "stopReason": event["messageStop"].get("stopReason"),
            }
            continue

        if "metadata" in event:
            metadata = event["metadata"]
            yield {
                "type": "metadata",
                "usage": _jsonable(metadata.get("usage", {})),
                "serviceLatencyMs": metadata.get("metrics", {}).get("latencyMs"),
            }
```

同ファイル冒頭の import を次に差し替えます（`Iterator` を追加）。

```python
from typing import Any, Iterable, Iterator
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd ~/workspace/agentcore-demo && ./.venv/bin/python -m unittest tests.test_chat_events -v`
Expected: PASS（6 tests）

- [ ] **Step 5: `parse_stream` をジェネレータの上に載せ替える**

`observability/invoke_harness.py` の `parse_stream` 本体（`for event in events:` から `return {...}` まで）を次に置き換えます。引数・戻り値・print の内容は変えません。

```python
def parse_stream(
    events: Iterable[dict[str, Any]],
    *,
    emit: bool = True,
    started_monotonic: float | None = None,
) -> dict[str, Any]:
    started = started_monotonic or time.monotonic()
    text_parts: list[str] = []
    tool_uses: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    usage: dict[str, int] = {}
    service_latency_ms: int | None = None
    first_token_ms: int | None = None
    stop_reason: str | None = None
    answer_started = False

    for event in iter_stream_events(events):
        kind = event["type"]

        if kind == "text":
            if first_token_ms is None:
                first_token_ms = round((time.monotonic() - started) * 1000)
            text_parts.append(event["text"])
            if emit:
                if not answer_started:
                    print("\n[answer]", flush=True)
                    answer_started = True
                print(event["text"], end="", flush=True)
        elif kind == "tool_use_start":
            if emit:
                print(f"\n[toolUse] {event['name']}", flush=True)
        elif kind == "tool_use_delta":
            if emit:
                print(event["fragment"], end="", flush=True)
        elif kind == "tool_use":
            tool_uses.append(event["block"])
            if emit:
                print("", flush=True)
        elif kind == "tool_result_start":
            if emit:
                print(
                    f"\n[toolResult] status={event['status'] or 'unknown'}",
                    flush=True,
                )
        elif kind == "tool_result_delta":
            if emit:
                print(_print_json(event["content"]), flush=True)
        elif kind == "tool_result":
            tool_results.append(event["block"])
        elif kind == "stop":
            stop_reason = event["stopReason"]
        elif kind == "metadata":
            usage = event["usage"]
            service_latency_ms = event["serviceLatencyMs"]

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
```

- [ ] **Step 6: 既存テストが壊れていないことを確認する**

Run: `cd ~/workspace/agentcore-demo && ./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`
Expected: PASS（既存 11 tests + 新規 6 tests = 17 tests）。とくに `test_projector_output_has_event_labels` と `test_parses_text_tools_and_metadata` が通ること

- [ ] **Step 7: Commit**

```bash
cd ~/workspace/agentcore-demo
git add observability/invoke_harness.py tests/test_chat_events.py
git commit -m "Refactor: ストリーム解析を iter_stream_events に切り出し parse_stream を載せ替え"
```

---

### Task 2: `chatui/harness_client.py`

**Files:**
- Create: `chatui/harness_client.py`
- Modify: `tests/test_chat_events.py`（`StreamTurnTest` を追記）

**Interfaces:**
- Consumes: Task 1 の `iter_stream_events`
- Produces: `new_session_id() -> str`（ハイフン付き UUID・36 文字）、`stream_turn(*, prompt, session_id, model_id, harness_arn, profile, region, actor_id) -> Iterator[dict[str, Any]]`。yield する `type` は `text` / `tool_use` / `tool_result` / `done` / `error`。`tool_use` は `{toolUseId, name, input}`、`tool_result` は `{toolUseId, status, content}`、`done` は `{firstTokenMs, elapsedMs, usage}`、`error` は `{message}`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_chat_events.py` の `if __name__ == "__main__":` の**直前**に追記します。

```python
class StreamTurnTest(unittest.TestCase):
    def _invoke(self, events: list[dict], **overrides):
        import harness_client

        client = mock.Mock()
        client.invoke_harness.return_value = {"stream": events}
        session = mock.Mock()
        session.client.return_value = client
        kwargs = {
            "prompt": "注文 A-100 の処理状況は？",
            "session_id": "9201016d-854f-40bf-a556-6c858f7b66c8",
            "model_id": None,
            "harness_arn": "arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:harness/Demo-abc",
            "profile": "default",
            "region": "ap-northeast-1",
            "actor_id": "chat-9201016d-854f-40bf-a556-6c858f7b66c8",
        }
        kwargs.update(overrides)
        with mock.patch.object(harness_client.boto3, "Session", return_value=session):
            return list(harness_client.stream_turn(**kwargs)), client

    def test_maps_stream_to_ui_events(self) -> None:
        events, _ = self._invoke(sample_events())

        types = [event["type"] for event in events]
        self.assertEqual(types, ["tool_use", "tool_result", "text", "text", "done"])

        tool_use = events[0]
        self.assertEqual(tool_use["name"], "inspect_order_lifecycle")
        self.assertEqual(tool_use["toolUseId"], "t-1")
        self.assertEqual(tool_use["input"], {"orderId": "A-100"})

        tool_result = events[1]
        self.assertEqual(tool_result["toolUseId"], "t-1")
        self.assertEqual(tool_result["status"], "success")

    def test_done_carries_latency_and_usage(self) -> None:
        events, _ = self._invoke(sample_events())

        done = events[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["usage"]["totalTokens"], 120)
        self.assertIsNotNone(done["firstTokenMs"])
        self.assertIsInstance(done["elapsedMs"], int)

    def test_error_event_becomes_error_and_stops(self) -> None:
        events, _ = self._invoke(
            [
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "途中まで"}}},
                {"validationException": {"message": "bad request"}},
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "続き"}}},
            ]
        )

        types = [event["type"] for event in events]
        self.assertEqual(types, ["text", "error"])
        self.assertIn("bad request", events[-1]["message"])

    def test_model_override_is_sent_only_when_given(self) -> None:
        _, client = self._invoke(sample_events(), model_id="jp.amazon.nova-2-lite-v1:0")
        request = client.invoke_harness.call_args.kwargs
        self.assertEqual(
            request["model"]["bedrockModelConfig"]["modelId"],
            "jp.amazon.nova-2-lite-v1:0",
        )

        _, client = self._invoke(sample_events())
        self.assertNotIn("model", client.invoke_harness.call_args.kwargs)

    def test_rejects_short_session_id(self) -> None:
        import harness_client

        with self.assertRaisesRegex(ValueError, "33"):
            list(
                harness_client.stream_turn(
                    prompt="hi",
                    session_id="short",
                    model_id=None,
                    harness_arn="arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:harness/Demo-abc",
                    profile="default",
                    region="ap-northeast-1",
                    actor_id="chat-short",
                )
            )

    def test_new_session_id_is_36_characters(self) -> None:
        import harness_client

        self.assertEqual(len(harness_client.new_session_id()), 36)
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd ~/workspace/agentcore-demo && ./.venv/bin/python -m unittest tests.test_chat_events -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'harness_client'`）

- [ ] **Step 3: `chatui/harness_client.py` を実装する**

```bash
cd ~/workspace/agentcore-demo && mkdir -p chatui && touch chatui/harness_client.py
```

```python
#!/usr/bin/env python3
"""チャット UI 向けに AgentCore Harness を呼び、扱いやすいイベントに正規化します。"""
from __future__ import annotations

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
MODEL_TEMPERATURE = 0.2


def new_session_id() -> str:
    """ハイフン付き UUID（36 文字）を返します。"""
    return str(uuid.uuid4())


def build_request(
    *,
    prompt: str,
    session_id: str,
    model_id: str | None,
    harness_arn: str,
    actor_id: str,
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
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd ~/workspace/agentcore-demo && ./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`
Expected: PASS（既存 11 + Task 1 の 6 + 今回の 6 = 23 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/workspace/agentcore-demo
git add chatui/harness_client.py tests/test_chat_events.py
git commit -m "Add: チャット UI 向けの Harness クライアント（stream_turn）"
```

---

### Task 3: `chatui/streamlit_app.py`

**Files:**
- Create: `chatui/streamlit_app.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: Task 2 の `new_session_id` / `stream_turn`
- Produces: `streamlit run chatui/streamlit_app.py` で動くアプリ。環境変数 `HARNESS_ARN` / `AWS_PROFILE` / `AWS_REGION` / `PRIMARY_MODEL_ID` / `ALTERNATE_MODEL_ID` を読む

- [ ] **Step 1: 依存を追加してインストールする**

`requirements.txt` を次にします。

```text
boto3>=1.43.16,<2
aws-opentelemetry-distro>=0.10.0,<1
streamlit>=1.62,<2
```

Run: `cd ~/workspace/agentcore-demo && ./.venv/bin/python -m pip install --quiet -r requirements.txt && ./.venv/bin/python -c "import streamlit; print(streamlit.__version__)"`
Expected: `1.62.0` 以上が表示される

- [ ] **Step 2: アプリを実装する**

```bash
cd ~/workspace/agentcore-demo && touch chatui/streamlit_app.py
```

```python
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

from harness_client import new_session_id, stream_turn  # noqa: E402

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
    with st.status(f"🔧 {block['name']}", state=state, expanded=False):
        st.caption("引数")
        st.code(as_json(block.get("input")), language="json")
        if block.get("content") is not None:
            st.caption(f"結果（status={block.get('status') or 'unknown'}）")
            st.code(as_json(block["content"]), language="json")


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
            widget = st.status(f"🔧 {event['name']}", state="running", expanded=False)
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
            widget.code(as_json(event["content"]), language="json")
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
```

- [ ] **Step 3: 構文と import を確認する**

Run: `cd ~/workspace/agentcore-demo && ./.venv/bin/python -c "import ast, pathlib; ast.parse(pathlib.Path('chatui/streamlit_app.py').read_text()); print('syntax OK')"`
Expected: `syntax OK`

- [ ] **Step 4: 既存テストが壊れていないことを確認する**

Run: `cd ~/workspace/agentcore-demo && ./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
Expected: PASS（23 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/workspace/agentcore-demo
git add chatui/streamlit_app.py requirements.txt
git commit -m "Add: Streamlit のチャット画面（ツール呼び出し・モデル切替・セッション表示）"
```

---

### Task 4: `scripts/chat.sh` と README、通し動作確認

**Files:**
- Create: `scripts/chat.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: `scripts/common.sh` の `require_no_args` / `require_tools` / `require_deployed` / `section`、Task 3 のアプリ
- Produces: `./scripts/chat.sh`（引数なし）

- [ ] **Step 1: 起動スクリプトを作る**

```bash
cd ~/workspace/agentcore-demo && touch scripts/chat.sh && chmod +x scripts/chat.sh
```

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/scripts/common.sh"
require_no_args "$@"
require_tools
require_deployed

section "CHAT UI"
printf 'Harness: %s\n' "${HARNESS_ID}"
printf 'URL: http://127.0.0.1:8787\n\n'

exec "${PYTHON}" -m streamlit run "${ROOT}/chatui/streamlit_app.py" \
  --server.address 127.0.0.1 \
  --server.port 8787 \
  --browser.gatherUsageStats false
```

- [ ] **Step 2: 起動前チェックが効くことを確認する**

Run: `cd ~/workspace/agentcore-demo && ./scripts/chat.sh extra-arg; echo "EXIT=$?"`
Expected: `このスクリプトは引数を受け取りません。` と `EXIT=64`（`require_no_args` が効いている）

- [ ] **Step 3: 実際に起動して画面を確認する**

Run: `cd ~/workspace/agentcore-demo && ./scripts/setup.sh`（デプロイ済みでなければ実行）、続けて `./scripts/chat.sh`

ブラウザで `http://127.0.0.1:8787` を開き、次を確認します。

1. `注文 A-100 の処理状況と配送状況、SKU-RED-01 の在庫を教えてください` と送ると、応答が流れながら 3 つのツール呼び出しが折りたたみで現れる
2. 各ツールを開くと引数 JSON と結果 JSON が見える
3. 応答の下に first / total とトークン数が出る
4. 続けて `私の名前はミナです` → `私の名前は？` と送ると「ミナ」と答える（session ID が変わっていないこと）
5. 「新しい会話」を押すと session ID が変わり、同じ質問に名前を答えられなくなる
6. モデルを alternate に切り替えて送ると、応答が返る

- [ ] **Step 4: 起動しっぱなしにしない**

Ctrl-C で Streamlit を止めます。デモが終わったら `./scripts/teardown.sh` で AWS リソースを削除します（チャット UI は AWS リソースを追加しないため、teardown の手順は変わりません）。

- [ ] **Step 5: README に節を追加する**

`README.md` の「クイックスタート」の直後に次を挿入します。

````markdown
### チャット画面から使う

スクリプトの代わりに、ブラウザのチャット画面から同じ Harness と会話できます。AWS リソースは追加しません。

```bash
./scripts/chat.sh
```

`http://127.0.0.1:8787` が開きます。応答のストリーミング、ツール呼び出しの引数と結果、レイテンシとトークン数、モデルの切り替え、session ID の表示と「新しい会話」でのリセットができます。
````

あわせて「ディレクトリ」節の `scripts/` の並びに次の 1 行を加えます。

```text
  chat.sh             チャット画面を起動する（Streamlit・ローカルのみ）
```

そして同じ節の末尾に次を加えます。

```text
chatui/               チャット画面（Streamlit アプリと Harness クライアント）
```

- [ ] **Step 6: Commit**

```bash
cd ~/workspace/agentcore-demo
git add scripts/chat.sh README.md
git commit -m "Add: チャット画面の起動スクリプトと README の手順"
```

---

## 完了条件

- `./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` が 23 tests PASS
- `npm test` が PASS（TypeScript 側 7 tests + Python 23 tests）
- `./scripts/chat.sh` で画面が開き、Task 4 Step 3 の 6 項目すべてを確認できる
- 5 本のステップスクリプトが従来どおり動く（`./scripts/step1-basic.sh` と `./scripts/step2-tool.sh` で確認）
- `git status` が clean
