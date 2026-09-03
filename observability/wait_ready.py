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
    gateway_id = os.environ["GATEWAY_ID"]
    target_id = os.environ["GATEWAY_TARGET_ID"]
    session = boto3.Session(profile_name=profile, region_name=region)
    control = session.client("bedrock-agentcore-control")
    deadline = time.monotonic() + TIMEOUT_SECONDS
    previous: str | None = None

    while time.monotonic() < deadline:
        target = control.get_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=target_id,
        )
        status = target["status"]
        if status != previous:
            print(f"GatewayTarget={status}", flush=True)
            previous = status
        if status in FAILED:
            raise RuntimeError(f"GatewayTarget failed: {target}")
        if status == "READY":
            return
        time.sleep(10)
    raise TimeoutError(f"GatewayTarget did not become READY in {TIMEOUT_SECONDS}s")


if __name__ == "__main__":
    main()
