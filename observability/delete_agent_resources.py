#!/usr/bin/env python3
"""teardown の前段: CDK 管理外で作った Harness と Online Evaluation を削除する。

Step 1（コンソール / CLI）と Step 5 で作ったリソースが対象。
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


def delete_evaluations(control, name: str) -> None:
    paginator = control.get_paginator("list_online_evaluation_configs")
    for page in paginator.paginate():
        for item in page.get("onlineEvaluationConfigs", []):
            if item.get("onlineEvaluationConfigName") != name:
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


def delete_harness(control, name: str) -> None:
    harness_id = None
    paginator = control.get_paginator("list_harnesses")
    for page in paginator.paginate():
        for item in page.get("harnesses", []):
            if item.get("harnessName") == name:
                harness_id = item["harnessId"]
    if harness_id is None:
        print(f"Harness {name} は存在しません（削除済み）。")
        return

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
    delete_harness(control, os.environ["HARNESS_NAME"])


if __name__ == "__main__":
    main()
