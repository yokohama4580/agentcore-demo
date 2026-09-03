#!/usr/bin/env python3
from __future__ import annotations

import os

import boto3


EVALUATION_LOG_PREFIX = (
    "/aws/bedrock-agentcore/evaluations/results/"
    "AsagaoSupportAgentEvaluation-"
)
HARNESS_LOG_PREFIX = (
    "/aws/bedrock-agentcore/runtimes/"
    "harness_AsagaoSupportAgent-"
)


def main() -> None:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    session = boto3.Session(profile_name=profile, region_name=region)
    logs = session.client("logs")
    names = []
    for prefix in (EVALUATION_LOG_PREFIX, HARNESS_LOG_PREFIX):
        response = logs.describe_log_groups(logGroupNamePrefix=prefix)
        names.extend(
            item["logGroupName"]
            for item in response.get("logGroups", [])
            if item["logGroupName"].startswith(prefix)
        )
    existing = {
        item["logGroupName"]
        for item in logs.describe_log_groups(
            logGroupNamePrefix="/aws/bedrock-agentcore/"
        ).get("logGroups", [])
    }
    for name in names:
        if name in existing:
            logs.delete_log_group(logGroupName=name)
            print(f"Deleted implicit log group: {name}")


if __name__ == "__main__":
    main()
