import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "observability"))
from show_scores import evaluation_summary  # noqa: E402


class EvaluationSummaryTest(unittest.TestCase):
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
                    "gen_ai.evaluation.name": "Builtin.GoalSuccessRate",
                    "gen_ai.evaluation.score": 0,
                    "session.id": "session-456",
                }
            }
        )

        self.assertEqual(
            evaluation_summary(message),
            ("Builtin.GoalSuccessRate", "0", "session-456"),
        )


if __name__ == "__main__":
    unittest.main()
