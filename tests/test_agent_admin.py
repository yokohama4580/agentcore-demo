import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chatui"))

import agent_admin  # noqa: E402

GATEWAY_ARN = "arn:aws:bedrock-agentcore:ap-northeast-1:000000000000:gateway/gw"
MODEL_ID = "jp.anthropic.claude-haiku-4-5-20251001-v1:0"
NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def harness(name: str, *, status: str = "READY", minutes: int = 0) -> dict:
    return {
        "harnessName": name,
        "harnessId": f"{name}-id",
        "arn": f"arn:aws:bedrock-agentcore:ap-northeast-1:000000000000:harness/{name}-id",
        "harnessVersion": "1",
        "status": status,
        "createdAt": NOW + timedelta(minutes=minutes),
        "environment": {
            "agentCoreRuntimeEnvironment": {
                "agentRuntimeId": f"harness_{name}-rt",
                "agentRuntimeName": f"harness_{name}",
            }
        },
        "model": {"bedrockModelConfig": {"modelId": MODEL_ID}},
    }


class FakePaginator:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages

    def paginate(self):
        return iter(self.pages)


class FakeControl:
    def __init__(self, harnesses: list[dict]) -> None:
        self.harnesses = harnesses
        self.created: list[dict] = []

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_harnesses"
        return FakePaginator([{"harnesses": self.harnesses}])

    def get_harness(self, harnessId: str) -> dict:
        for item in self.harnesses:
            if item["harnessId"] == harnessId:
                return {"harness": item}
        raise AssertionError(harnessId)

    def create_harness(self, **params) -> dict:
        self.created.append(params)
        created = harness(params["harnessName"], status="CREATING")
        created["model"] = params["model"]
        return {"harness": created}


class LoadSpecTest(unittest.TestCase):
    def test_placeholders_are_replaced(self) -> None:
        spec = agent_admin.load_spec(gateway_arn=GATEWAY_ARN, model_id=MODEL_ID)
        self.assertEqual(spec["harnessName"], "AsagaoSupportAgent")
        self.assertEqual(spec["model"]["bedrockModelConfig"]["modelId"], MODEL_ID)
        gateway = spec["tools"][0]["config"]["agentCoreGateway"]["gatewayArn"]
        self.assertEqual(gateway, GATEWAY_ARN)
        self.assertEqual(spec["model"]["bedrockModelConfig"]["temperature"], 0.0)


class NormalizeTest(unittest.TestCase):
    def test_normalize_extracts_runtime_and_log_group(self) -> None:
        item = agent_admin.normalize(harness("AsagaoSupportAgent"))
        self.assertEqual(item["harnessId"], "AsagaoSupportAgent-id")
        self.assertEqual(item["runtimeName"], "harness_AsagaoSupportAgent")
        self.assertEqual(
            item["logGroup"],
            "/aws/bedrock-agentcore/runtimes/harness_AsagaoSupportAgent-rt-DEFAULT",
        )
        self.assertEqual(item["createdAt"], NOW.isoformat())

    def test_missing_runtime_leaves_log_group_empty(self) -> None:
        item = agent_admin.normalize(
            {"harnessName": "x", "harnessId": "x-id", "status": "CREATING"}
        )
        self.assertEqual(item["logGroup"], "")
        self.assertEqual(item["status"], "CREATING")


class ResolveTest(unittest.TestCase):
    def test_picks_newest_and_falls_back_to_newest_ready(self) -> None:
        control = FakeControl(
            [
                harness("AsagaoSupportAgent", minutes=0),
                harness("AsagaoSupportAgentLive", status="CREATING", minutes=10),
                harness("OtherAgent", minutes=20),
            ]
        )
        state = agent_admin.resolve_agents(control, "AsagaoSupportAgent")
        self.assertEqual(state["count"], 2)
        self.assertEqual(state["current"]["harnessName"], "AsagaoSupportAgentLive")
        self.assertEqual(state["usable"]["harnessName"], "AsagaoSupportAgent")

    def test_ready_newest_is_used_directly(self) -> None:
        control = FakeControl(
            [
                harness("AsagaoSupportAgent", minutes=0),
                harness("AsagaoSupportAgentLive", minutes=10),
            ]
        )
        state = agent_admin.resolve_agents(control, "AsagaoSupportAgent")
        self.assertEqual(state["usable"]["harnessName"], "AsagaoSupportAgentLive")

    def test_no_agent_returns_empty_state(self) -> None:
        state = agent_admin.resolve_agents(FakeControl([]), "AsagaoSupportAgent")
        self.assertIsNone(state["current"])
        self.assertIsNone(state["usable"])
        self.assertEqual(state["count"], 0)


class SuggestNameTest(unittest.TestCase):
    def test_base_name_when_free(self) -> None:
        self.assertEqual(
            agent_admin.suggest_name(FakeControl([]), "AsagaoSupportAgent"),
            "AsagaoSupportAgent",
        )

    def test_suffix_when_taken(self) -> None:
        control = FakeControl([harness("AsagaoSupportAgent")])
        self.assertEqual(
            agent_admin.suggest_name(control, "AsagaoSupportAgent"),
            "AsagaoSupportAgentLive",
        )

    def test_numbered_suffix_when_live_taken(self) -> None:
        control = FakeControl(
            [harness("AsagaoSupportAgent"), harness("AsagaoSupportAgentLive")]
        )
        self.assertEqual(
            agent_admin.suggest_name(control, "AsagaoSupportAgent"),
            "AsagaoSupportAgentLive2",
        )


class CreateAgentTest(unittest.TestCase):
    def test_create_applies_name_role_tag_and_overrides(self) -> None:
        control = FakeControl([])
        spec = agent_admin.load_spec(gateway_arn=GATEWAY_ARN, model_id=MODEL_ID)
        created = agent_admin.create_agent(
            control,
            spec=spec,
            role_arn="arn:aws:iam::000000000000:role/HarnessRole",
            harness_name="AsagaoSupportAgentLive",
            model_id="jp.amazon.nova-2-lite-v1:0",
            system_prompt="別の指示",
        )
        params = control.created[0]
        self.assertEqual(params["harnessName"], "AsagaoSupportAgentLive")
        self.assertEqual(
            params["executionRoleArn"], "arn:aws:iam::000000000000:role/HarnessRole"
        )
        self.assertEqual(params["tags"], {"Project": "agentcore-support-demo"})
        self.assertEqual(
            params["model"]["bedrockModelConfig"]["modelId"],
            "jp.amazon.nova-2-lite-v1:0",
        )
        # temperature などの他の宣言は harness.json のまま残る
        self.assertEqual(params["model"]["bedrockModelConfig"]["temperature"], 0.0)
        self.assertEqual(params["systemPrompt"], [{"text": "別の指示"}])
        self.assertEqual(created["status"], "CREATING")

    def test_create_keeps_spec_defaults_when_no_override(self) -> None:
        control = FakeControl([])
        spec = agent_admin.load_spec(gateway_arn=GATEWAY_ARN, model_id=MODEL_ID)
        agent_admin.create_agent(
            control,
            spec=spec,
            role_arn="arn:aws:iam::000000000000:role/HarnessRole",
            harness_name="AsagaoSupportAgent",
        )
        params = control.created[0]
        self.assertEqual(params["model"]["bedrockModelConfig"]["modelId"], MODEL_ID)
        self.assertEqual(params["systemPrompt"], spec["systemPrompt"])


class ConsoleValuesTest(unittest.TestCase):
    def test_values_for_console_form(self) -> None:
        spec = agent_admin.load_spec(gateway_arn=GATEWAY_ARN, model_id=MODEL_ID)
        values = agent_admin.console_values(
            spec,
            harness_name="AsagaoSupportAgentLive",
            role_arn="arn:aws:iam::000000000000:role/HarnessRole",
            gateway_arn=GATEWAY_ARN,
            region="ap-northeast-1",
        )
        self.assertEqual(values["harnessName"], "AsagaoSupportAgentLive")
        self.assertEqual(values["gatewayArn"], GATEWAY_ARN)
        self.assertIn("SEMANTIC", values["memory"])
        self.assertIn("bedrock-agentcore", values["consoleUrl"])
        self.assertEqual(values["tag"], "Project=agentcore-support-demo")


class ConfigureLogGroupTest(unittest.TestCase):
    class FakeLogs:
        def __init__(self, existing: list[str]) -> None:
            self.existing = existing
            self.retention: list[tuple[str, int]] = []
            self.tags: list[str] = []

        def describe_log_groups(self, logGroupNamePrefix: str) -> dict:
            return {
                "logGroups": [
                    {"logGroupName": name}
                    for name in self.existing
                    if name.startswith(logGroupNamePrefix)
                ]
            }

        def put_retention_policy(self, logGroupName: str, retentionInDays: int) -> None:
            self.retention.append((logGroupName, retentionInDays))

        def tag_log_group(self, logGroupName: str, tags: dict) -> None:
            self.tags.append(logGroupName)

    def test_sets_retention_and_tag_when_present(self) -> None:
        logs = self.FakeLogs(["/aws/bedrock-agentcore/runtimes/x-DEFAULT"])
        done = agent_admin.configure_log_group(
            logs, "/aws/bedrock-agentcore/runtimes/x-DEFAULT"
        )
        self.assertTrue(done)
        self.assertEqual(
            logs.retention, [("/aws/bedrock-agentcore/runtimes/x-DEFAULT", 3)]
        )
        self.assertEqual(logs.tags, ["/aws/bedrock-agentcore/runtimes/x-DEFAULT"])

    def test_absent_log_group_is_not_an_error(self) -> None:
        logs = self.FakeLogs([])
        self.assertFalse(
            agent_admin.configure_log_group(
                logs, "/aws/bedrock-agentcore/runtimes/x-DEFAULT"
            )
        )
        self.assertFalse(agent_admin.configure_log_group(logs, ""))


if __name__ == "__main__":
    unittest.main()
