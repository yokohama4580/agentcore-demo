import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "observability"))
from show_traces import evaluation_summary, latest_failed_tool_selection  # noqa: E402


class ShowTracesTest(unittest.TestCase):
    def test_extracts_evaluation_result_fields(self) -> None:
        message = json.dumps(
            {
                "evaluator": {"id": "Builtin.ToolSelectionAccuracy"},
                "score": 0,
                "session": {"id": "session-123"},
            }
        )

        self.assertEqual(
            evaluation_summary(message),
            ("Builtin.ToolSelectionAccuracy", "0", "session-123"),
        )

    def test_extracts_gen_ai_evaluation_name(self) -> None:
        message = json.dumps(
            {
                "attributes": {
                    "gen_ai.evaluation.name": "Builtin.ToolSelectionAccuracy",
                    "gen_ai.evaluation.score": 0,
                    "session.id": "session-456",
                }
            }
        )

        self.assertEqual(
            evaluation_summary(message),
            ("Builtin.ToolSelectionAccuracy", "0", "session-456"),
        )

    def test_selects_latest_failed_tool_selection(self) -> None:
        passing = json.dumps(
            {
                "attributes": {
                    "gen_ai.evaluation.name": "Builtin.ToolSelectionAccuracy",
                    "gen_ai.evaluation.score.value": 1.0,
                    "session.id": "passing-session",
                }
            }
        )
        failing = json.dumps(
            {
                "attributes": {
                    "gen_ai.evaluation.name": "Builtin.ToolSelectionAccuracy",
                    "gen_ai.evaluation.score.value": 0.0,
                    "session.id": "failing-session",
                }
            }
        )
        logs = _Logs([passing, failing])

        row = latest_failed_tool_selection(logs, log_group="evaluation-log")

        self.assertIsNotNone(row)
        self.assertEqual(row["@message"], failing)


class _Logs:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages

    def start_query(self, **_kwargs: object) -> dict[str, str]:
        return {"queryId": "query-1"}

    def get_query_results(self, **_kwargs: object) -> dict[str, object]:
        return {
            "status": "Complete",
            "results": [
                [{"field": "@message", "value": message}]
                for message in self.messages
            ],
        }


if __name__ == "__main__":
    unittest.main()
