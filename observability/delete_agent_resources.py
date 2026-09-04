#!/usr/bin/env python3
"""teardown の前段: CDK 管理外で作った Harness と Online Evaluation を削除する。

Step 1（画面 / コンソール / CLI）と Step 5 で作ったリソースが対象。
デモ中に作るエージェントは名前に接尾辞が付くことがある（AsagaoSupportAgentLive など）ため、
どちらも名前の前方一致で拾って全部削除する。
Harness が自動プロビジョニングした managed Memory の削除は
wait_agentcore_deleted.py（Project タグ起点）が引き受ける。
"""
from __future__ import annotations

import os
import time

import boto3
from botocore.exceptions import ClientError


def is_not_found(error: ClientError) -> bool:
    code = error.response.get("Error", {}).get("Code", "")
    return code in {"ResourceNotFoundException", "NotFoundException"} or (
        "not found" in str(error).lower()
    )


def delete_evaluations(control, base_name: str) -> None:
    paginator = control.get_paginator("list_online_evaluation_configs")
    for page in paginator.paginate():
        for item in page.get("onlineEvaluationConfigs", []):
            name = str(item.get("onlineEvaluationConfigName", ""))
            if not name.startswith(base_name):
                continue
            config_id = item["onlineEvaluationConfigId"]
            try:
                control.delete_online_evaluation_config(
                    onlineEvaluationConfigId=config_id
                )
                print(f"Online Evaluation を削除しました: {config_id}")
            except ClientError as error:
                if not is_not_found(error):
                    raise


def delete_harnesses(control, base_name: str) -> None:
    harness_ids: list[str] = []
    paginator = control.get_paginator("list_harnesses")
    for page in paginator.paginate():
        for item in page.get("harnesses", []):
            if str(item.get("harnessName", "")).startswith(base_name):
                harness_ids.append(item["harnessId"])
    if not harness_ids:
        print(f"Harness {base_name}* は存在しません（削除済み）。")
        return
    for harness_id in harness_ids:
        delete_harness(control, harness_id)


def delete_harness(control, harness_id: str) -> None:
    try:
        control.delete_harness(harnessId=harness_id)
        print(f"Harness の削除を開始しました: {harness_id}")
    except ClientError as error:
        if not is_not_found(error):
            raise
        return

    for _ in range(120):
        try:
            control.get_harness(harnessId=harness_id)
        except ClientError as error:
            if is_not_found(error):
                print("Harness の削除が完了しました。")
                return
            raise
        time.sleep(5)
    raise TimeoutError(f"Harness deletion did not finish: {harness_id}")


def main() -> None:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    session = boto3.Session(profile_name=profile, region_name=region)
    control = session.client("bedrock-agentcore-control")
    delete_evaluations(control, os.environ["EVALUATION_NAME"])
    delete_harnesses(control, os.environ["HARNESS_NAME"])


if __name__ == "__main__":
    main()
