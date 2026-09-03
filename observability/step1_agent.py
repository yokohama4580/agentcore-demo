#!/usr/bin/env python3
"""Step 1: Harness（エージェント本体）を作り、READY まで待つ。

既定はコンソール作成の伴走モード。ウィザードに貼る値を表示し、
コンソールでの作成完了を検知して READY まで待つ。
STEP1_MODE=cli なら CreateHarness API で同じ内容を直接作成する。
どちらの経路でも、READY 後にロググループの保持期間とタグを設定する。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "agentcore-support-demo"
FAILED = {"FAILED", "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"}
WAIT_TIMEOUT_SECONDS = 1800


def load_spec() -> dict:
    raw = (ROOT / "harness" / "harness.json").read_text(encoding="utf-8")
    raw = raw.replace("${GATEWAY_ARN}", os.environ["GATEWAY_ARN"])
    raw = raw.replace("${PRIMARY_MODEL_ID}", os.environ["PRIMARY_MODEL_ID"])
    return json.loads(raw)


def find_harness(control, name: str) -> dict | None:
    paginator = control.get_paginator("list_harnesses")
    for page in paginator.paginate():
        for item in page.get("harnesses", []):
            if item.get("harnessName") == name:
                return item
    return None


def print_console_values(spec: dict, region: str) -> None:
    console_url = (
        f"https://{region}.console.aws.amazon.com/bedrock-agentcore/home"
        f"?region={region}"
    )
    print("コンソールで Harness を作成する場合は、次の値を使ってください。\n")
    print(f"  コンソール: {console_url}")
    print(f"  名前:       {spec['harnessName']}")
    print(f"  実行ロール:  {os.environ['HARNESS_ROLE_ARN']}")
    print(f"  モデル:      {spec['model']['bedrockModelConfig']['modelId']}")
    print(f"  Gateway:    {os.environ['GATEWAY_ARN']}")
    print("  Memory:     SEMANTIC + SUMMARIZATION（保持 3 日）")
    print(f"  タグ:       Project={PROJECT}  ※teardown が削除対象を特定する鍵")
    print("  System prompt:")
    print(f"    {spec['systemPrompt'][0]['text']}")
    print(
        "\n作成したら、この画面のまま待ってください。"
        "READY を検知したら次に進みます。\n"
    )


def create_via_cli(control, spec: dict) -> None:
    params = dict(spec)
    params["executionRoleArn"] = os.environ["HARNESS_ROLE_ARN"]
    params["tags"] = {"Project": PROJECT}
    control.create_harness(**params)
    print(f"CreateHarness を発行しました: {spec['harnessName']}")


def wait_ready(control, name: str) -> dict:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    previous = None
    while time.monotonic() < deadline:
        summary = find_harness(control, name)
        if summary is None:
            if previous != "NOT_CREATED":
                print("Harness はまだ作成されていません…（コンソールでの作成を待っています）")
                previous = "NOT_CREATED"
            time.sleep(10)
            continue
        harness = control.get_harness(harnessId=summary["harnessId"])["harness"]
        status = harness["status"]
        if status != previous:
            print(f"Harness={status}", flush=True)
            previous = status
        if status in FAILED:
            raise RuntimeError(f"Harness failed: {harness}")
        if status == "READY":
            return harness
        time.sleep(10)
    raise TimeoutError(f"Harness did not become READY in {WAIT_TIMEOUT_SECONDS}s")


def configure_log_group(session: boto3.Session, log_group: str) -> None:
    logs = session.client("logs")
    for _ in range(60):
        response = logs.describe_log_groups(logGroupNamePrefix=log_group)
        if any(
            item["logGroupName"] == log_group
            for item in response.get("logGroups", [])
        ):
            logs.put_retention_policy(logGroupName=log_group, retentionInDays=3)
            logs.tag_log_group(logGroupName=log_group, tags={"Project": PROJECT})
            print(f"ロググループを設定しました: {log_group}")
            return
        time.sleep(5)
    print(f"注意: ロググループが見つかりません（初回呼び出し後に作成されます）: {log_group}")


def main() -> None:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    mode = os.environ.get("STEP1_MODE", "console")
    session = boto3.Session(profile_name=profile, region_name=region)
    control = session.client("bedrock-agentcore-control")
    spec = load_spec()
    name = spec["harnessName"]

    existing = find_harness(control, name)
    if existing is not None:
        print(f"Harness {name} は既に存在します。READY を確認します。")
    elif mode == "cli":
        create_via_cli(control, spec)
    else:
        print_console_values(spec, region)

    harness = wait_ready(control, name)
    runtime = harness.get("environment", {}).get(
        "agentCoreRuntimeEnvironment", {}
    )
    runtime_id = runtime.get("agentRuntimeId", "")
    log_group = f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"

    print(f"\nHarness READY: {harness['arn']}")
    print(f"version: {harness.get('harnessVersion', '1')}")
    if runtime_id:
        configure_log_group(session, log_group)


if __name__ == "__main__":
    try:
        main()
    except ClientError as error:
        raise SystemExit(f"Harness 作成に失敗しました: {error}") from error
