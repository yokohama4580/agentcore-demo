#!/usr/bin/env python3
from __future__ import annotations

import os
import time

import boto3


TIMEOUT_SECONDS = 1200
FAILED = {"FAILED", "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"}


def main() -> None:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    harness_id = os.environ["HARNESS_ID"]
    gateway_id = os.environ["GATEWAY_ID"]
    target_id = os.environ["GATEWAY_TARGET_ID"]
    session = boto3.Session(profile_name=profile, region_name=region)
    control = session.client("bedrock-agentcore-control")
    deadline = time.monotonic() + TIMEOUT_SECONDS
    previous: tuple[str, str] | None = None

    while time.monotonic() < deadline:
        harness = control.get_harness(harnessId=harness_id)["harness"]
        target = control.get_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=target_id,
        )
        statuses = (harness["status"], target["status"])
        if statuses != previous:
            print(f"Harness={statuses[0]} GatewayTarget={statuses[1]}", flush=True)
            previous = statuses
        if any(status in FAILED for status in statuses):
            raise RuntimeError(
                f"Resource failed: harness={harness} target={target}"
            )
        if statuses == ("READY", "READY"):
            return
        time.sleep(10)
    raise TimeoutError(f"Resources did not become READY in {TIMEOUT_SECONDS}s")


if __name__ == "__main__":
    main()
