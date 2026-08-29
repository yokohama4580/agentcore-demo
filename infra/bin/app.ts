#!/usr/bin/env node
import { App, Aspects } from "aws-cdk-lib";
import { AwsSolutionsChecks } from "cdk-nag";
import { AgentCoreDemoStack } from "../lib/agentcore-demo-stack";

// The approved deployment target is declared in .demo.env, never inferred.
// Deploying into an unapproved account or Region is refused below.
const APPROVED_ACCOUNT = process.env.APPROVED_ACCOUNT_ID;
const APPROVED_REGION = process.env.APPROVED_REGION;
const account = process.env.AWS_ACCOUNT_ID ?? process.env.CDK_DEFAULT_ACCOUNT;
const region =
  process.env.AWS_REGION ??
  process.env.AWS_DEFAULT_REGION ??
  process.env.CDK_DEFAULT_REGION;

if (
  !APPROVED_ACCOUNT ||
  !APPROVED_REGION ||
  account !== APPROVED_ACCOUNT ||
  region !== APPROVED_REGION
) {
  throw new Error(
    "Refusing unapproved CDK target: " +
      `account=${account ?? "unset"} region=${region ?? "unset"} ` +
      `approved=${APPROVED_ACCOUNT ?? "unset"}/${APPROVED_REGION ?? "unset"}. ` +
      "Set APPROVED_ACCOUNT_ID and APPROVED_REGION in .demo.env.",
  );
}

const app = new App();

new AgentCoreDemoStack(app, process.env.STACK_NAME ?? "AgentCoreSupportDemo", {
  env: { account, region },
  description: "Amazon Bedrock AgentCore support agent demo",
});

Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));
