import json
import os
import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from server import app as server_app  # noqa: E402

DEMO_ENV = {
    "AWS_PROFILE": "default",
    "AWS_REGION": "ap-northeast-1",
    "PRIMARY_MODEL_ID": "jp.anthropic.claude-haiku-4-5-20251001-v1:0",
    "ALTERNATE_MODEL_ID": "jp.amazon.nova-2-lite-v1:0",
    "HARNESS_NAME": "AsagaoSupportAgent",
    "HARNESS_ROLE_ARN": "arn:aws:iam::000000000000:role/HarnessRole",
    "GATEWAY_ARN": "arn:aws:bedrock-agentcore:ap-northeast-1:000000000000:gateway/gw",
    "EVALUATION_NAME": "AsagaoSupportAgentEvaluation",
    "DASHBOARD_NAME": "agentcore-support-demo",
}

AGENT = {
    "harnessName": "AsagaoSupportAgentLive",
    "harnessId": "AsagaoSupportAgentLive-abc123",
    "harnessArn": (
        "arn:aws:bedrock-agentcore:ap-northeast-1:000000000000:"
        "harness/AsagaoSupportAgentLive-abc123"
    ),
    "harnessVersion": "1",
    "status": "READY",
    "failureReason": None,
    "modelId": DEMO_ENV["PRIMARY_MODEL_ID"],
    "runtimeId": "harness_AsagaoSupportAgentLive-xyz",
    "runtimeName": "harness_AsagaoSupportAgentLive",
    "logGroup": (
        "/aws/bedrock-agentcore/runtimes/harness_AsagaoSupportAgentLive-xyz-DEFAULT"
    ),
    "createdAt": "2026-09-04T00:00:00+00:00",
}

STATE = {
    "current": AGENT,
    "usable": AGENT,
    "count": 1,
    "baseName": "AsagaoSupportAgent",
    "suggestedName": "AsagaoSupportAgentLive2",
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
    def test_config_returns_models_console_urls_and_definition(self) -> None:
        with mock.patch.dict(os.environ, DEMO_ENV):
            client = TestClient(server_app.app)
            response = client.get("/api/config")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["models"]["primary"], DEMO_ENV["PRIMARY_MODEL_ID"])
        self.assertEqual(body["harnessBaseName"], "AsagaoSupportAgent")
        self.assertIn("gen-ai-observability", body["consoleUrls"]["genaiObservability"])
        self.assertIn("evaluations", body["consoleUrls"]["evaluations"])
        self.assertGreaterEqual(len(body["sessionId"]), 33)
        definition = body["definition"]
        self.assertEqual(definition["modelId"], DEMO_ENV["PRIMARY_MODEL_ID"])
        self.assertTrue(definition["systemPrompt"])
        names = [tool["name"] for tool in definition["gatewayTools"]]
        self.assertIn("inspect_order_lifecycle", names)
        self.assertIn("lookup_inventory", names)


class AgentEndpointTest(unittest.TestCase):
    def test_agent_returns_state_and_console_values(self) -> None:
        with mock.patch.dict(os.environ, DEMO_ENV), mock.patch.object(
            server_app, "agent_state", lambda force=False: dict(STATE)
        ):
            client = TestClient(server_app.app)
            response = client.get("/api/agent")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["usable"]["harnessId"], AGENT["harnessId"])
        self.assertEqual(
            body["consoleValues"]["harnessName"], "AsagaoSupportAgentLive2"
        )
        self.assertEqual(
            body["consoleValues"]["executionRoleArn"], DEMO_ENV["HARNESS_ROLE_ARN"]
        )
        self.assertIn("Project=agentcore-support-demo", body["consoleValues"]["tag"])
        self.assertIn(
            urllib.parse.quote(AGENT["logGroup"], safe=""),
            body["consoleUrls"]["harnessLogs"],
        )

    def test_create_agent_rejects_name_outside_base(self) -> None:
        with mock.patch.dict(os.environ, DEMO_ENV):
            client = TestClient(server_app.app)
            response = client.post("/api/agent", json={"harnessName": "OtherAgent"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("AsagaoSupportAgent", response.json()["detail"])


class ChatStreamTest(unittest.TestCase):
    def run_chat(
        self, payload: dict, fake_events: list[dict]
    ) -> tuple[list[dict], dict]:
        captured: dict = {}

        def fake_stream_turn(**kwargs):
            captured.update(kwargs)
            yield from fake_events

        with mock.patch.dict(os.environ, DEMO_ENV), mock.patch.object(
            server_app, "stream_turn", fake_stream_turn
        ), mock.patch.object(
            server_app, "agent_state", lambda force=False: dict(STATE)
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
        self.assertEqual(captured["harness_arn"], AGENT["harnessArn"])
        self.assertIsNone(captured.get("system_prompt"))
        self.assertIsNone(captured["model_id"])

    def test_model_override_passes_through(self) -> None:
        _, captured = self.run_chat(
            {
                "prompt": "status?",
                "sessionId": SESSION_ID,
                "modelId": DEMO_ENV["ALTERNATE_MODEL_ID"],
            },
            [{"type": "done", "firstTokenMs": None, "elapsedMs": 1, "usage": {}}],
        )
        self.assertEqual(captured["model_id"], DEMO_ENV["ALTERNATE_MODEL_ID"])
        self.assertIsNone(captured.get("system_prompt"))

    def test_chat_without_agent_returns_conflict(self) -> None:
        empty = {"current": None, "usable": None, "count": 0}
        with mock.patch.dict(os.environ, DEMO_ENV), mock.patch.object(
            server_app, "agent_state", lambda force=False: dict(empty)
        ):
            client = TestClient(server_app.app)
            response = client.post(
                "/api/chat", json={"prompt": "hi", "sessionId": SESSION_ID}
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Step 1", response.json()["detail"])

    def test_rejects_short_session_id(self) -> None:
        with mock.patch.dict(os.environ, DEMO_ENV):
            client = TestClient(server_app.app)
            response = client.post(
                "/api/chat", json={"prompt": "hi", "sessionId": "short"}
            )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
