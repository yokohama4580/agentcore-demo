#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from urllib.parse import unquote

import boto3
from botocore.exceptions import ClientError


PROJECT = "agentcore-support-demo"


def is_not_found(error: ClientError) -> bool:
    code = error.response.get("Error", {}).get("Code", "")
    return code in {"ResourceNotFoundException", "NotFoundException"} or (
        "does not exist" in str(error) or "not found" in str(error).lower()
    )


def tagged_resource_exists(
    arn: str,
    *,
    session: boto3.Session,
) -> bool:
    control = session.client("bedrock-agentcore-control")
    resource = arn.split(":", 5)[-1]
    try:
        if resource.startswith("harness/"):
            control.get_harness(harnessId=resource.split("/")[1])
        elif resource.startswith("runtime/"):
            control.get_agent_runtime(agentRuntimeId=resource.split("/")[1])
        elif resource.startswith("memory/"):
            control.get_memory(memoryId=resource.split("/")[1])
        elif resource.startswith("gateway/"):
            control.get_gateway(gatewayIdentifier=resource.split("/")[1])
        elif resource.startswith("online-evaluation-config/"):
            control.get_online_evaluation_config(
                onlineEvaluationConfigId=resource.split("/")[1]
            )
        elif resource.startswith("workload-identity-directory/"):
            control.get_workload_identity(name=resource.rsplit("/", 1)[-1])
        elif ":function:" in arn:
            session.client("lambda").get_function(FunctionName=arn.rsplit(":", 1)[-1])
        elif ":log-group:" in arn:
            name = unquote(arn.split(":log-group:", 1)[1]).split(":log-stream:", 1)[0]
            groups = session.client("logs").describe_log_groups(
                logGroupNamePrefix=name,
                limit=1,
            ).get("logGroups", [])
            return bool(groups and groups[0]["logGroupName"] == name)
        elif ":cloudformation:" in arn:
            session.client("cloudformation").describe_stacks(StackName=arn)
        elif ":apigateway:" in arn and "/restapis/" in arn:
            api_id = arn.split("/restapis/", 1)[1].split("/", 1)[0]
            session.client("apigateway").get_rest_api(restApiId=api_id)
        else:
            return True
    except ClientError as error:
        if is_not_found(error):
            return False
        raise
    return True


def main() -> int:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    stack_name = os.environ.get("STACK_NAME", "AgentCoreSupportDemo")
    session = boto3.Session(profile_name=profile, region_name=region)
    leftovers: list[str] = []
    stale_tag_index: list[str] = []

    cfn = session.client("cloudformation")
    try:
        status = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["StackStatus"]
        leftovers.append(f"CloudFormation stack {stack_name}: {status}")
    except ClientError as error:
        if not is_not_found(error):
            raise

    backup_recovery_points: list[str] = []
    tagging = session.client("resourcegroupstaggingapi")
    paginator = tagging.get_paginator("get_resources")
    for page in paginator.paginate(
        TagFilters=[{"Key": "Project", "Values": [PROJECT]}]
    ):
        for item in page["ResourceTagMappingList"]:
            arn = item["ResourceARN"]
            if ":backup:" in arn and ":recovery-point:" in arn:
                # AWS Backup のバックアップ計画がデモスタックを保護対象に
                # 取り込むと、タグが伝播した復旧ポイントが作られる。
                # デモのスクリプトが作るものではなく、バックアップの自動削除は
                # 安全側に倒して行わない（別枠で表示だけする）。
                backup_recovery_points.append(arn)
                continue
            if tagged_resource_exists(arn, session=session):
                leftovers.append(arn)
            else:
                stale_tag_index.append(arn)

    control = session.client("bedrock-agentcore-control")
    for item in control.list_harnesses().get("harnesses", []):
        if item.get("harnessName") == "AsagaoSupportAgent":
            leftovers.append(f"Harness {item.get('harnessArn', item)}")
    for item in control.list_gateways().get("items", []):
        if item.get("name") == "agentcore-support-demo-gateway":
            leftovers.append(f"Gateway {item.get('gatewayArn', item)}")
    for item in control.list_online_evaluation_configs().get(
        "onlineEvaluationConfigs", []
    ):
        if (
            item.get("onlineEvaluationConfigName")
            == "AsagaoSupportAgentEvaluation"
        ):
            leftovers.append(f"OnlineEvaluation {item}")

    for item in control.list_agent_runtimes().get("agentRuntimes", []):
        if item.get("agentRuntimeName") == "harness_AsagaoSupportAgent":
            leftovers.append(f"Runtime {item}")
    for item in control.list_workload_identities().get("workloadIdentities", []):
        if item.get("name", "").startswith("harness_AsagaoSupportAgent-"):
            leftovers.append(f"WorkloadIdentity {item}")

    lambda_client = session.client("lambda")
    for page in lambda_client.get_paginator("list_functions").paginate():
        for item in page.get("Functions", []):
            if item["FunctionName"].startswith(f"{stack_name}-"):
                leftovers.append(f"Lambda {item['FunctionArn']}")

    api_gateway = session.client("apigateway")
    for item in api_gateway.get_rest_apis(limit=500).get("items", []):
        if item.get("name") == "ToolsApi":
            leftovers.append(f"API Gateway {item['id']}")

    logs = session.client("logs")
    for prefix in (stack_name, "/aws/bedrock-agentcore/"):
        for item in logs.describe_log_groups(logGroupNamePrefix=prefix).get(
            "logGroups", []
        ):
            name = item["logGroupName"]
            if (
                stack_name in name
                or "AgentCoreSupportDemo" in name
                or "AsagaoSupportAgent" in name
            ):
                leftovers.append(f"LogGroup {name}")

    iam = session.client("iam")
    for page in iam.get_paginator("list_roles").paginate(PathPrefix="/"):
        for item in page.get("Roles", []):
            if item["RoleName"].startswith(f"{stack_name}-"):
                leftovers.append(f"IAM Role {item['Arn']}")

    dashboards = session.client("cloudwatch").list_dashboards(
        DashboardNamePrefix="agentcore-support-demo"
    )
    for item in dashboards.get("DashboardEntries", []):
        leftovers.append(f"Dashboard {item['DashboardName']}")

    for item in session.client("s3").list_buckets().get("Buckets", []):
        if PROJECT in item["Name"]:
            leftovers.append(f"S3 Bucket {item['Name']}")

    if backup_recovery_points:
        print("デモが作成しないリソース（アカウントのバックアップ計画由来・削除しない）:")
        for item in sorted(backup_recovery_points):
            print(f"- {item}")
    leftovers = sorted(set(leftovers))
    if leftovers:
        print("残存リソース:")
        for item in leftovers:
            print(f"- {item}")
        return 1
    if stale_tag_index:
        print("削除済みだが Tagging API 索引に残る ARN:")
        for item in sorted(stale_tag_index):
            print(f"- {item}")
    print("Project=agentcore-support-demo の残存リソース: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
