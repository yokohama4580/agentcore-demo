#!/usr/bin/env python3
from __future__ import annotations

import os
import time

import boto3
from botocore.exceptions import ClientError


EVALUATION_LOG_PREFIX = (
    "/aws/bedrock-agentcore/evaluations/results/"
    "AgentCoreSupportDemoEvaluation-"
)


def configure(logs: object, log_group: str) -> None:
    logs.put_retention_policy(logGroupName=log_group, retentionInDays=3)
    logs.tag_log_group(
        logGroupName=log_group,
        tags={"Project": "agentcore-support-demo"},
    )
    print(f"Configured log retention/tag: {log_group}")


def main() -> None:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    log_group = os.environ["HARNESS_LOG_GROUP"]
    session = boto3.Session(profile_name=profile, region_name=region)
    logs = session.client("logs")

    for _ in range(60):
        response = logs.describe_log_groups(logGroupNamePrefix=log_group)
        if any(
            item["logGroupName"] == log_group
            for item in response.get("logGroups", [])
        ):
            configure(logs, log_group)
            break
        time.sleep(5)
    else:
        raise TimeoutError(f"Harness log group did not appear: {log_group}")

    for _ in range(60):
        response = logs.describe_log_groups(
            logGroupNamePrefix=EVALUATION_LOG_PREFIX
        )
        matching = [
            item["logGroupName"]
            for item in response.get("logGroups", [])
            if item["logGroupName"].startswith(EVALUATION_LOG_PREFIX)
        ]
        if matching:
            for evaluation_log_group in matching:
                configure(logs, evaluation_log_group)
            return
        time.sleep(5)
    raise TimeoutError("Evaluation result log group did not appear")


if __name__ == "__main__":
    try:
        main()
    except ClientError as error:
        raise SystemExit(f"CloudWatch Logs configuration failed: {error}") from error
