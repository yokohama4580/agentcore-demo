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


class DisplayHelperTest(unittest.TestCase):
    def test_short_tool_name_drops_gateway_target_prefix(self) -> None:
        import harness_client

        self.assertEqual(
            harness_client.short_tool_name(
                "order-operations-api___inspect_order_lifecycle"
            ),
            "inspect_order_lifecycle",
        )
        self.assertEqual(
            harness_client.short_tool_name("lookup_inventory"),
            "lookup_inventory",
        )

    def test_unwrap_tool_content_parses_nested_json_text(self) -> None:
        import harness_client

        content = [{"text": '{"source":"orders","data":{"status":"PROCESSING"}}'}]

        self.assertEqual(
            harness_client.unwrap_tool_content(content),
            {"source": "orders", "data": {"status": "PROCESSING"}},
        )

    def test_unwrap_tool_content_keeps_unparsable_items(self) -> None:
        import harness_client

        content = [{"text": "not json"}, {"json": {"a": 1}}]

        self.assertEqual(
            harness_client.unwrap_tool_content(content),
            [{"text": "not json"}, {"json": {"a": 1}}],
        )

    def test_unwrap_tool_content_passes_through_non_list(self) -> None:
        import harness_client

        self.assertIsNone(harness_client.unwrap_tool_content(None))


if __name__ == "__main__":
    unittest.main()
