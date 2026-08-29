import assert from "node:assert/strict";
import test from "node:test";
import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
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

test("creates a managed harness with explicit limits and memory", () => {
  const synthesized = template();
  synthesized.hasResourceProperties("AWS::BedrockAgentCore::Harness", {
    HarnessName: "AgentCoreSupportDemo",
    MaxIterations: 8,
    MaxTokens: 2048,
    TimeoutSeconds: 120,
    Memory: {
      ManagedMemoryConfiguration: {
        Strategies: ["SEMANTIC", "SUMMARIZATION"],
        EventExpiryDuration: 3,
      },
    },
    Model: {
      BedrockModelConfig: Match.objectLike({
        ModelId: "jp.anthropic.claude-haiku-4-5-20251001-v1:0",
        MaxTokens: 1024,
      }),
    },
  });
  const harness = Object.values(
    synthesized.findResources("AWS::BedrockAgentCore::Harness"),
  )[0] as { Properties: { Model: { BedrockModelConfig: { TopP?: number } } } };
  assert.equal(harness.Properties.Model.BedrockModelConfig.TopP, undefined);
});

test("creates gateway and online tool evaluations", () => {
  const synthesized = template();
  synthesized.resourceCountIs("AWS::BedrockAgentCore::Gateway", 1);
  synthesized.resourceCountIs("AWS::BedrockAgentCore::GatewayTarget", 1);
  synthesized.hasResourceProperties(
    "AWS::BedrockAgentCore::OnlineEvaluationConfig",
    {
      Evaluators: [
        { EvaluatorId: "Builtin.ToolSelectionAccuracy" },
        { EvaluatorId: "Builtin.ToolParameterAccuracy" },
      ],
      ExecutionStatus: "ENABLED",
      Rule: Match.objectLike({
        SamplingConfig: {
          SamplingPercentage: 100,
        },
      }),
    },
  );
});

test("limits Gateway API invocation to the three GET fixture paths", () => {
  const rendered = JSON.stringify(template().toJSON());
  assert.doesNotMatch(rendered, /\/demo\/\*\/\*/);
  assert.match(rendered, /\/demo\/GET\/orders\/\*/);
  assert.match(rendered, /\/demo\/GET\/inventory\/\*/);
  assert.match(rendered, /\/demo\/GET\/shipments\/\*/);
});

test("grants the harness access to its managed memory", () => {
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
  assert.match(
    JSON.stringify(memoryStatement.Resource),
    /memory\/AgentCoreSupportDemo-\*/,
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
    { Type: string; Properties?: Record<string, unknown> }
  >;
  const harness = Object.values(resources).find(
    (resource) => resource.Type === "AWS::BedrockAgentCore::Harness",
  );
  assert.ok(harness);
  assert.deepEqual(harness.Properties?.Tags, [
    {
      Key: "Project",
      Value: "agentcore-support-demo",
    },
  ]);
});
