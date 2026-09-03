#!/usr/bin/env python3
from __future__ import annotations

import os
import time

import boto3
from botocore.exceptions import ClientError


PROJECT = "agentcore-support-demo"
MEMORY_ARN_MARKER = ":memory/"


def is_not_found(error: ClientError) -> bool:
    code = error.response.get("Error", {}).get("Code", "")
    return code == "ResourceNotFoundException" or "not found" in str(error).lower()


def main() -> int:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    session = boto3.Session(profile_name=profile, region_name=region)
    tagging = session.client("resourcegroupstaggingapi")
    control = session.client("bedrock-agentcore-control")

    memory_ids: set[str] = set()
    paginator = tagging.get_paginator("get_resources")
    for page in paginator.paginate(
        TagFilters=[{"Key": "Project", "Values": [PROJECT]}]
    ):
        for item in page["ResourceTagMappingList"]:
            arn = item["ResourceARN"]
            if MEMORY_ARN_MARKER in arn:
                memory_ids.add(arn.split(MEMORY_ARN_MARKER, 1)[1])

    for attempt in range(61):
        remaining: list[tuple[str, str]] = []
        for memory_id in sorted(memory_ids):
            try:
                memory = control.get_memory(memoryId=memory_id)["memory"]
            except ClientError as error:
                if is_not_found(error):
                    continue
                raise
            status = memory.get("status", "UNKNOWN")
            remaining.append((memory_id, status))
            if status != "DELETING":
                control.delete_memory(memoryId=memory_id)
                print(f"Started managed Memory deletion: {memory_id}")

        if not remaining:
            print("Managed Memory deletion complete.")
            return 0
        if attempt == 60:
            break
        if attempt % 6 == 0:
            detail = ", ".join(f"{memory_id}={status}" for memory_id, status in remaining)
            print(f"Waiting for managed Memory deletion: {detail}")
        time.sleep(5)

    print("Managed Memory deletion timed out:")
    for memory_id, status in remaining:
        print(f"- {memory_id}: {status}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
