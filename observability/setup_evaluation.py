#!/usr/bin/env python3
"""Step 5: Online Evaluation を有効化する（存在しなければ作成する）。

本番トラフィックを LLM-as-a-Judge が継続採点する仕組みを、稼働中の
エージェントに後付けする。コンソールから作成しても同じ内容になる。
"""
from __future__ import annotations

import os
import time

import boto3
from botocore.exceptions import ClientError

PROJECT = "agentcore-support-demo"
EVALUATOR_IDS = [
    "Builtin.GoalSuccessRate",
    "Builtin.Helpfulness",
    "Builtin.ToolSelectionAccuracy",
    "Builtin.ToolParameterAccuracy",
]


def find_config(control, name: str) -> dict | None:
    paginator = control.get_paginator("list_online_evaluation_configs")
    for page in paginator.paginate():
        for item in page.get("onlineEvaluationConfigs", []):
            if item.get("onlineEvaluationConfigName") == name:
                return item
    return None


def configure_results_log_group(session: boto3.Session, config_id: str) -> None:
    logs = session.client("logs")
    log_group = f"/aws/bedrock-agentcore/evaluations/results/{config_id}"
    for _ in range(60):
        response = logs.describe_log_groups(logGroupNamePrefix=log_group)
        if any(
            item["logGroupName"] == log_group
            for item in response.get("logGroups", [])
        ):
            logs.put_retention_policy(logGroupName=log_group, retentionInDays=3)
            logs.tag_log_group(logGroupName=log_group, tags={"Project": PROJECT})
            print(f"結果ロググループを設定しました: {log_group}")
            return
        time.sleep(5)
    print(f"注意: 結果ロググループはまだありません（初回採点時に作成されます）: {log_group}")


def main() -> None:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    name = os.environ["EVALUATION_NAME"]
    session = boto3.Session(profile_name=profile, region_name=region)
    control = session.client("bedrock-agentcore-control")

    existing = find_config(control, name)
    if existing is not None:
        config_id = existing["onlineEvaluationConfigId"]
        print(f"Online Evaluation は既に存在します: {config_id}")
    else:
        runtime_name = os.environ["HARNESS_RUNTIME_NAME"]
        response = control.create_online_evaluation_config(
            onlineEvaluationConfigName=name,
            description=(
                "Continuously scores the Asagao support agent's production "
                "traffic with LLM-as-a-Judge evaluators"
            ),
            rule={
                "samplingConfig": {"samplingPercentage": 100.0},
                "sessionConfig": {"sessionTimeoutMinutes": 1},
            },
            dataSourceConfig={
                "cloudWatchLogs": {
                    "logGroupNames": [os.environ["HARNESS_LOG_GROUP"]],
                    "serviceNames": [f"{runtime_name}.DEFAULT"],
                }
            },
            evaluators=[{"evaluatorId": item} for item in EVALUATOR_IDS],
            evaluationExecutionRoleArn=os.environ["EVALUATION_ROLE_ARN"],
            enableOnCreate=True,
            tags={"Project": PROJECT},
        )
        config = response.get("onlineEvaluationConfig", response)
        config_id = config.get("onlineEvaluationConfigId", "")
        print(f"Online Evaluation を作成しました: {config_id}")
        print(f"評価器: {', '.join(EVALUATOR_IDS)}")
        print("サンプリング 100%（デモ用。本番は 1〜5% が公式ブログの推奨）")

    if config_id:
        configure_results_log_group(session, config_id)


if __name__ == "__main__":
    try:
        main()
    except ClientError as error:
        raise SystemExit(f"Online Evaluation の設定に失敗しました: {error}") from error
