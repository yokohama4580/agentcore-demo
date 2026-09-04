import assert from "node:assert/strict";
import test from "node:test";
import { App } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { AgentCoreDemoStack } from "../lib/agentcore-demo-stack";

function template(): Template {
  const app = new App();
  const stack = new AgentCoreDemoStack(app, "TestStack", {
    env: {
      account: "111122223333",
      region: "ap-northeast-1",
    },
  });
  return Template.fromStack(stack);
}

test("creates three IAM-protected API methods", () => {
  const synthesized = template();
  synthesized.resourceCountIs("AWS::ApiGateway::Method", 3);
  synthesized.allResourcesProperties("AWS::ApiGateway::Method", {
    AuthorizationType: "AWS_IAM",
    MethodResponses: [{ StatusCode: "200" }, { StatusCode: "404" }],
  });
});

test("does not create the harness or evaluation config in CDK", () => {
  // Step 1 of the demo story creates the Harness in the console (or CLI),
  // and Step 5 creates the online evaluation config. The stack only
  // provides the surrounding infrastructure and execution roles.
  const synthesized = template();
  synthesized.resourceCountIs("AWS::BedrockAgentCore::Harness", 0);
  synthesized.resourceCountIs(
    "AWS::BedrockAgentCore::OnlineEvaluationConfig",
    0,
  );
});

test("creates the gateway with a single target", () => {
  const synthesized = template();
  synthesized.resourceCountIs("AWS::BedrockAgentCore::Gateway", 1);
  synthesized.resourceCountIs("AWS::BedrockAgentCore::GatewayTarget", 1);
});

test("exports the names and role ARNs used by Step 1 and Step 5", () => {
  const outputs = template().toJSON().Outputs as Record<string, unknown>;
  for (const key of [
    "HarnessName",
    "HarnessRoleArn",
    "EvaluationName",
    "EvaluationRoleArn",
    "GatewayArn",
  ]) {
    assert.ok(key in outputs, `missing output: ${key}`);
  }
});

test("limits Gateway API invocation to the three GET fixture paths", () => {
  const rendered = JSON.stringify(template().toJSON());
  assert.doesNotMatch(rendered, /\/demo\/\*\/\*/);
  assert.match(rendered, /\/demo\/GET\/orders\/\*/);
  assert.match(rendered, /\/demo\/GET\/inventory\/\*/);
  assert.match(rendered, /\/demo\/GET\/shipments\/\*/);
});

test("grants the harness role access to its managed memory", () => {
  const resources = template().toJSON().Resources as Record<
    string,
    {
      Type: string;
      Properties?: {
        PolicyDocument?: { Statement?: Array<Record<string, unknown>> };
        Roles?: Array<{ Ref?: string }>;
      };
    }
  >;
  const harnessPolicy = Object.values(resources).find(
    (resource) =>
      resource.Type === "AWS::IAM::Policy" &&
      resource.Properties?.Roles?.some(
        (role) => role.Ref === "HarnessRoleB55BF37F",
      ),
  );
  assert.ok(harnessPolicy);
  const memoryStatement =
    harnessPolicy.Properties?.PolicyDocument?.Statement?.find(
      (statement) =>
        Array.isArray(statement.Action) &&
        statement.Action.includes("bedrock-agentcore:ListEvents"),
    );
  assert.ok(memoryStatement);
  assert.deepEqual(memoryStatement.Action, [
    "bedrock-agentcore:CreateEvent",
    "bedrock-agentcore:DeleteEvent",
    "bedrock-agentcore:GetEvent",
    "bedrock-agentcore:ListEvents",
    "bedrock-agentcore:RetrieveMemoryRecords",
  ]);
  // デモ中に作る AsagaoSupportAgentLive などの managed Memory も含む前方一致であること
  assert.match(
    JSON.stringify(memoryStatement.Resource),
    /memory\/AsagaoSupportAgent\*/,
  );
});

test("lets the evaluation role write results for suffixed config names", () => {
  // Step 5 をコンソールから作ると名前に接尾辞が付くことがある。ハイフン止まりの
  // 前方一致だと CreateOnlineEvaluationConfig が ValidationException で落ちる
  const rendered = JSON.stringify(template().toJSON());
  assert.match(
    rendered,
    /\/aws\/bedrock-agentcore\/evaluations\/results\/AsagaoSupportAgentEvaluation\*/,
  );
  assert.doesNotMatch(
    rendered,
    /\/aws\/bedrock-agentcore\/evaluations\/results\/AsagaoSupportAgentEvaluation-\*/,
  );
});

test("allows evaluations to correlate split telemetry spans", () => {
  const rendered = JSON.stringify(template().toJSON());
  assert.match(rendered, /logs:DescribeIndexPolicies/);
  assert.match(rendered, /logs:PutIndexPolicy/);
  assert.match(rendered, /log-group:aws\/spans/);
});

test("all taggable resources receive the project tag", () => {
  const resources = template().toJSON().Resources as Record<
    string,
    { Type: string; Properties?: { Tags?: unknown } }
  >;
  const gateway = Object.values(resources).find(
    (resource) => resource.Type === "AWS::BedrockAgentCore::Gateway",
  );
  assert.ok(gateway);
  assert.match(JSON.stringify(gateway.Properties?.Tags), /agentcore-support-demo/);
});
