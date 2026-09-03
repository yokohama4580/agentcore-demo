import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from server import app as server_app  # noqa: E402

DEMO_ENV = {
    "HARNESS_ARN": "arn:aws:bedrock-agentcore:ap-northeast-1:000000000000:harness/demo",
    "HARNESS_ID": "demo-harness",
    "HARNESS_VERSION": "1",
    "HARNESS_LOG_GROUP": "/aws/bedrock-agentcore/runtimes/demo-DEFAULT",
    "AWS_PROFILE": "default",
    "AWS_REGION": "ap-northeast-1",
    "PRIMARY_MODEL_ID": "jp.anthropic.claude-haiku-4-5-20251001-v1:0",
    "ALTERNATE_MODEL_ID": "jp.amazon.nova-2-lite-v1:0",
}

SESSION_ID = "12345678-1234-1234-1234-123456789012"


def parse_sse(body: str) -> list[dict]:
    events = []
    for chunk in body.split("\n\n"):
        line = chunk.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


class ConfigTest(unittest.TestCase):
    def test_config_returns_models_and_console_urls(self) -> None:
        with mock.patch.dict(os.environ, DEMO_ENV):
            client = TestClient(server_app.app)
            response = client.get("/api/config")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["harnessId"], "demo-harness")
        self.assertEqual(body["models"]["primary"], DEMO_ENV["PRIMARY_MODEL_ID"])
        self.assertIn("gen-ai-observability", body["consoleUrls"]["genaiObservability"])
        self.assertIn("evaluations", body["consoleUrls"]["evaluations"])
        self.assertGreaterEqual(len(body["sessionId"]), 33)


class ChatStreamTest(unittest.TestCase):
    def run_chat(self, payload: dict, fake_events: list[dict]) -> tuple[list[dict], dict]:
        captured: dict = {}

        def fake_stream_turn(**kwargs):
            captured.update(kwargs)
            yield from fake_events

        with mock.patch.dict(os.environ, DEMO_ENV), mock.patch.object(
            server_app, "stream_turn", fake_stream_turn
        ):
            client = TestClient(server_app.app)
            response = client.post("/api/chat", json=payload)
        self.assertEqual(response.status_code, 200)
        return parse_sse(response.text), captured

    def test_chat_streams_events_as_sse(self) -> None:
        fake_events = [
            {"type": "text", "text": "こんにちは"},
            {
                "type": "done",
                "firstTokenMs": 100,
                "elapsedMs": 200,
                "usage": {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3},
            },
        ]
        events, captured = self.run_chat(
            {"prompt": "hi", "sessionId": SESSION_ID}, fake_events
        )
        self.assertEqual(events, fake_events)
        self.assertEqual(captured["session_id"], SESSION_ID)
        self.assertIsNone(captured["system_prompt"])
        self.assertIsNone(captured["model_id"])

    def test_fault_injection_sets_system_prompt(self) -> None:
        _, captured = self.run_chat(
            {
                "prompt": "status?",
                "sessionId": SESSION_ID,
                "modelId": DEMO_ENV["ALTERNATE_MODEL_ID"],
                "faultInjection": True,
            },
            [{"type": "done", "firstTokenMs": None, "elapsedMs": 1, "usage": {}}],
        )
        self.assertEqual(captured["system_prompt"], server_app.FAULT_SYSTEM_PROMPT)
        self.assertEqual(captured["model_id"], DEMO_ENV["ALTERNATE_MODEL_ID"])

    def test_rejects_short_session_id(self) -> None:
        with mock.patch.dict(os.environ, DEMO_ENV):
            client = TestClient(server_app.app)
            response = client.post(
                "/api/chat", json={"prompt": "hi", "sessionId": "short"}
            )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
