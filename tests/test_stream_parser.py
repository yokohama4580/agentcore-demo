import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "observability"))
from invoke_harness import parse_stream  # noqa: E402
from measure_wrong_tool import matches_tool_name, wilson_interval  # noqa: E402


class StreamParserTest(unittest.TestCase):
    def test_parses_text_tools_and_metadata(self) -> None:
        events = [
            {"messageStart": {"role": "assistant"}},
            {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {
                        "toolUse": {
                            "toolUseId": "tool-1",
                            "name": "lookup_order_status",
                        }
                    },
                }
            },
            {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"toolUse": {"input": '{"order'}},
                }
            },
            {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"toolUse": {"input": 'Id":"A-100"}'}},
                }
            },
            {"contentBlockStop": {"contentBlockIndex": 0}},
            {
                "contentBlockStart": {
                    "contentBlockIndex": 1,
                    "start": {
                        "toolResult": {
                            "toolUseId": "tool-1",
                            "status": "success",
                        }
                    },
                }
            },
            {
                "contentBlockDelta": {
                    "contentBlockIndex": 1,
                    "delta": {
                        "toolResult": [
                            {"json": {"source": "shipments", "status": "DELIVERED"}}
                        ]
                    },
                }
            },
            {"contentBlockStop": {"contentBlockIndex": 1}},
            {
                "contentBlockDelta": {
                    "contentBlockIndex": 2,
                    "delta": {"text": "配送済みです。"},
                }
            },
            {"contentBlockStop": {"contentBlockIndex": 2}},
            {"messageStop": {"stopReason": "end_turn"}},
            {
                "metadata": {
                    "usage": {
                        "inputTokens": 100,
                        "outputTokens": 20,
                        "totalTokens": 120,
                    },
                    "metrics": {"latencyMs": 321},
                }
            },
        ]

        result = parse_stream(events, emit=False)

        self.assertEqual(result["responseText"], "配送済みです。")
        self.assertEqual(result["toolUses"][0]["name"], "lookup_order_status")
        self.assertEqual(result["toolUses"][0]["input"], {"orderId": "A-100"})
        self.assertEqual(result["toolResults"][0]["status"], "success")
        self.assertEqual(result["usage"]["totalTokens"], 120)
        self.assertEqual(result["serviceLatencyMs"], 321)
        self.assertEqual(result["stopReason"], "end_turn")

    def test_projector_output_has_event_labels(self) -> None:
        events = [
            {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {
                        "toolUse": {"toolUseId": "1", "name": "lookup_inventory"}
                    },
                }
            },
            {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"toolUse": {"input": '{"sku":"SKU-RED-01"}'}},
                }
            },
            {"contentBlockStop": {"contentBlockIndex": 0}},
            {
                "contentBlockDelta": {
                    "contentBlockIndex": 1,
                    "delta": {"text": "在庫は4点です。"},
                }
            },
        ]
        output = io.StringIO()
        with redirect_stdout(output):
            parse_stream(events)
        self.assertIn("[toolUse] lookup_inventory", output.getvalue())
        self.assertIn("[answer]", output.getvalue())

    def test_runtime_error_event_fails(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "failed"):
            parse_stream(
                [{"runtimeClientError": {"message": "failed"}}],
                emit=False,
            )

    def test_wilson_interval_contains_observed_rate(self) -> None:
        low, high = wilson_interval(14, 20)
        self.assertLess(low, 0.7)
        self.assertGreater(high, 0.7)

    def test_matches_gateway_qualified_tool_name(self) -> None:
        self.assertTrue(
            matches_tool_name(
                "order-operations-api___lookup_order_shipment_status",
                "lookup_order_shipment_status",
            )
        )
        self.assertFalse(
            matches_tool_name(
                "order-operations-api___inspect_order_lifecycle",
                "lookup_order_shipment_status",
            )
        )


if __name__ == "__main__":
    unittest.main()
