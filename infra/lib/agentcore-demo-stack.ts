import * as path from "node:path";
import {
  Arn,
  ArnFormat,
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
} from "aws-cdk-lib";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as agentcore from "aws-cdk-lib/aws-bedrockagentcore";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

const PROJECT = "agentcore-support-demo";
const STAGE = "demo";
const PRIMARY_MODEL = "jp.anthropic.claude-haiku-4-5-20251001-v1:0";
const ALTERNATE_MODEL = "jp.amazon.nova-2-lite-v1:0";
// The Harness itself is created outside CDK (console or CLI) in Step 1 of the
// demo story. The stack provides everything the Harness needs: the tools API,
// the Gateway, and pre-created execution roles for the Harness / Evaluations.
const HARNESS_NAME = "AsagaoSupportAgent";
const EVALUATION_NAME = "AsagaoSupportAgentEvaluation";

export class AgentCoreDemoStack extends Stack {
  constructor(scope: Construct, id: string, props: StackProps) {
    super(scope, id, props);

    Tags.of(this).add("Project", PROJECT);

    const apiLogGroup = new logs.LogGroup(this, "ApiAccessLogs", {
      retention: logs.RetentionDays.THREE_DAYS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const functionLogGroup = new logs.LogGroup(this, "ToolsFunctionLogs", {
      retention: logs.RetentionDays.THREE_DAYS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const functionRole = new iam.Role(this, "ToolsFunctionRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description: "Execution role for the fixture-only tools API",
    });
    functionRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
        resources: [`${functionLogGroup.logGroupArn}:*`],
      }),
    );
    functionRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
        resources: ["*"],
      }),
    );

    const toolsFunction = new lambda.Function(this, "ToolsFunction", {
      runtime: lambda.Runtime.PYTHON_3_14,
      architecture: lambda.Architecture.ARM_64,
      handler: "handler.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../../tools-api")),
      description: "Fixture-only REST API for AgentCore demo tools",
      memorySize: 256,
      timeout: Duration.seconds(5),
      reservedConcurrentExecutions: 2,
      tracing: lambda.Tracing.ACTIVE,
      logGroup: functionLogGroup,
      role: functionRole,
    });

    const api = new apigateway.RestApi(this, "ToolsApi", {
      description: "Existing order operations API exposed to AgentCore",
      endpointTypes: [apigateway.EndpointType.REGIONAL],
      cloudWatchRole: true,
      cloudWatchRoleRemovalPolicy: RemovalPolicy.DESTROY,
      deployOptions: {
        stageName: STAGE,
        accessLogDestination: new apigateway.LogGroupLogDestination(
          apiLogGroup,
        ),
        accessLogFormat: apigateway.AccessLogFormat.jsonWithStandardFields({
          caller: true,
          httpMethod: true,
          ip: true,
          protocol: true,
          requestTime: true,
          resourcePath: true,
          responseLength: true,
          status: true,
          user: true,
        }),
        metricsEnabled: true,
        loggingLevel: apigateway.MethodLoggingLevel.ERROR,
        dataTraceEnabled: false,
        tracingEnabled: true,
        throttlingBurstLimit: 5,
        throttlingRateLimit: 2,
      },
    });

    const integration = new apigateway.LambdaIntegration(toolsFunction, {
      proxy: true,
      allowTestInvoke: true,
    });
    const requestValidator = api.addRequestValidator("PathParameterValidator", {
      requestValidatorName: "agentcore-demo-path-parameters",
      validateRequestBody: true,
      validateRequestParameters: true,
    });
    const orderMethodOptions: apigateway.MethodOptions = {
      authorizationType: apigateway.AuthorizationType.IAM,
      requestValidator,
      requestParameters: {
        "method.request.path.orderId": true,
      },
      methodResponses: [{ statusCode: "200" }, { statusCode: "404" }],
    };
    const skuMethodOptions: apigateway.MethodOptions = {
      authorizationType: apigateway.AuthorizationType.IAM,
      requestValidator,
      requestParameters: {
        "method.request.path.sku": true,
      },
      methodResponses: [{ statusCode: "200" }, { statusCode: "404" }],
    };

    const orders = api.root.addResource("orders");
    const order = orders.addResource("{orderId}");
    const orderMethod = order.addMethod("GET", integration, orderMethodOptions);
    (orderMethod.node.defaultChild as apigateway.CfnMethod).operationName =
      "getOrderStatus";

    const inventory = api.root.addResource("inventory");
    const inventoryItem = inventory.addResource("{sku}");
    const inventoryMethod = inventoryItem.addMethod(
      "GET",
      integration,
      skuMethodOptions,
    );
    (inventoryMethod.node.defaultChild as apigateway.CfnMethod).operationName =
      "getInventory";

    const shipments = api.root.addResource("shipments");
    const shipment = shipments.addResource("{orderId}");
    const shipmentMethod = shipment.addMethod(
      "GET",
      integration,
      orderMethodOptions,
    );
    (shipmentMethod.node.defaultChild as apigateway.CfnMethod).operationName =
      "getShipmentStatus";

    const gatewayRole = new iam.Role(this, "GatewayRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", {
        conditions: {
          StringEquals: {
            "aws:SourceAccount": this.account,
          },
          ArnLike: {
            "aws:SourceArn": Arn.format(
              {
                service: "bedrock-agentcore",
                resource: "gateway",
                resourceName: "*",
                arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
              },
              this,
            ),
          },
        },
      }),
      description: "AgentCore Gateway role scoped to the demo REST API",
    });
    gatewayRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["execute-api:Invoke"],
        resources: [
          api.arnForExecuteApi("GET", "/orders/*", STAGE),
          api.arnForExecuteApi("GET", "/inventory/*", STAGE),
          api.arnForExecuteApi("GET", "/shipments/*", STAGE),
        ],
      }),
    );

    const gateway = new agentcore.Gateway(this, "Gateway", {
      gatewayName: "agentcore-support-demo-gateway",
      description: "MCP facade for the existing order operations API",
      protocolConfiguration: agentcore.GatewayProtocol.mcp({
        instructions:
          "Use these read-only tools for order, inventory, and shipment support questions.",
        searchType: agentcore.McpGatewaySearchType.SEMANTIC,
        supportedVersions: [agentcore.MCPProtocolVersion.MCP_2025_06_18],
      }),
      authorizerConfiguration: agentcore.GatewayAuthorizer.usingAwsIam(),
      role: gatewayRole,
      tags: {
        Project: PROJECT,
      },
    });

    const gatewayTarget = new agentcore.CfnGatewayTarget(
      this,
      "GatewayTarget",
      {
        gatewayIdentifier: gateway.gatewayId,
        name: "order-operations-api",
        description: "Existing REST API converted to MCP tools",
        credentialProviderConfigurations: [
          {
            credentialProviderType: "GATEWAY_IAM_ROLE",
          },
        ],
        targetConfiguration: {
          mcp: {
            apiGateway: {
              restApiId: api.restApiId,
              stage: STAGE,
              apiGatewayToolConfiguration: {
                toolFilters: [
                  {
                    filterPath: "/orders/{orderId}",
                    methods: ["GET"],
                  },
                  {
                    filterPath: "/inventory/{sku}",
                    methods: ["GET"],
                  },
                  {
                    filterPath: "/shipments/{orderId}",
                    methods: ["GET"],
                  },
                ],
                toolOverrides: [
                  {
                    path: "/orders/{orderId}",
                    method: "GET",
                    name: "inspect_order_lifecycle",
                    description:
                      "Look up the order-management lifecycle state. Returns the order's processing, payment, and cancellation status only.",
                  },
                  {
                    path: "/inventory/{sku}",
                    method: "GET",
                    name: "lookup_inventory",
                    description:
                      "Look up available and reserved inventory for a SKU.",
                  },
                  {
                    path: "/shipments/{orderId}",
                    method: "GET",
                    name: "lookup_order_shipment_status",
                    description:
                      "Look up the current carrier-side delivery state for an order. Use for shipment, delivery, carrier, or ETA questions.",
                  },
                ],
              },
            },
          },
        },
      },
    );
    gatewayTarget.node.addDependency(api.deploymentStage);
    gatewayTarget.node.addDependency(
      gatewayRole.node.findChild("DefaultPolicy"),
    );

    const harnessRole = new iam.Role(this, "HarnessRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", {
        conditions: {
          StringEquals: {
            "aws:SourceAccount": this.account,
          },
          ArnLike: {
            "aws:SourceArn": [
              Arn.format(
                {
                  service: "bedrock-agentcore",
                  resource: "harness",
                  resourceName: "*",
                  arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
                },
                this,
              ),
              Arn.format(
                {
                  service: "bedrock-agentcore",
                  resource: "runtime",
                  resourceName: "*",
                  arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
                },
                this,
              ),
            ],
          },
        },
      }),
      description: "Execution role for the managed AgentCore Harness",
    });
    harnessRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:Converse",
          "bedrock:ConverseStream",
        ],
        resources: [
          Arn.format(
            {
              service: "bedrock",
              resource: "inference-profile",
              resourceName: PRIMARY_MODEL,
              arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
            },
            this,
          ),
          Arn.format(
            {
              service: "bedrock",
              resource: "inference-profile",
              resourceName: ALTERNATE_MODEL,
              arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
            },
            this,
          ),
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:*::foundation-model/amazon.nova-2-lite-v1:0",
        ],
      }),
    );
    harnessRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock-agentcore:InvokeGateway"],
        resources: [gateway.gatewayArn],
      }),
    );
    harnessRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "bedrock-agentcore:CreateEvent",
          "bedrock-agentcore:DeleteEvent",
          "bedrock-agentcore:GetEvent",
          "bedrock-agentcore:ListEvents",
          "bedrock-agentcore:RetrieveMemoryRecords",
        ],
        resources: [
          Arn.format(
            {
              service: "bedrock-agentcore",
              resource: "memory",
              // デモ中に作るエージェントは名前に接尾辞が付く（AsagaoSupportAgentLive など）。
              // managed Memory の名前もそれに続くので、ハイフンを含めない前方一致にする
              resourceName: `${HARNESS_NAME}*`,
              arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
            },
            this,
          ),
        ],
      }),
    );
    const harnessRuntimeLogGroupsArn = Arn.format(
      {
        service: "logs",
        resource: "log-group",
        resourceName: "/aws/bedrock-agentcore/runtimes/*",
        arnFormat: ArnFormat.COLON_RESOURCE_NAME,
      },
      this,
    );
    harnessRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "logs:CreateLogGroup",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
        ],
        resources: [harnessRuntimeLogGroupsArn],
      }),
    );
    harnessRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
        resources: [`${harnessRuntimeLogGroupsArn}:log-stream:*`],
      }),
    );
    harnessRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
          "xray:PutTelemetryRecords",
          "xray:PutTraceSegments",
        ],
        resources: ["*"],
      }),
    );
    harnessRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["cloudwatch:PutMetricData"],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "cloudwatch:namespace": "bedrock-agentcore",
          },
        },
      }),
    );

    const sharedSpansLogGroupArn = Arn.format(
      {
        service: "logs",
        resource: "log-group",
        resourceName: "aws/spans",
        arnFormat: ArnFormat.COLON_RESOURCE_NAME,
      },
      this,
    );

    const evaluationRole = new iam.Role(this, "EvaluationRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", {
        conditions: {
          StringEquals: {
            "aws:SourceAccount": this.account,
          },
          ArnLike: {
            "aws:SourceArn": Arn.format(
              {
                service: "bedrock-agentcore",
                resource: "online-evaluation-config",
                resourceName: "*",
                arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
              },
              this,
            ),
          },
        },
      }),
      description: "Reads only the demo Harness traces for Evaluations",
    });
    evaluationRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["logs:DescribeLogGroups", "logs:GetQueryResults"],
        resources: ["*"],
      }),
    );
    evaluationRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["logs:StartQuery"],
        resources: [harnessRuntimeLogGroupsArn, sharedSpansLogGroupArn],
      }),
    );
    evaluationRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["logs:DescribeIndexPolicies", "logs:PutIndexPolicy"],
        resources: [sharedSpansLogGroupArn, `${sharedSpansLogGroupArn}:*`],
      }),
    );
    const evaluationResultsLogGroupsArn = Arn.format(
      {
        service: "logs",
        resource: "log-group",
        // Step 5 はコンソールから作ることもあり、名前に接尾辞が付く場合がある
        // （AsagaoSupportAgentEvaluationLive など）。ハイフンを含めない前方一致にする
        resourceName: `/aws/bedrock-agentcore/evaluations/results/${EVALUATION_NAME}*`,
        arnFormat: ArnFormat.COLON_RESOURCE_NAME,
      },
      this,
    );
    evaluationRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["logs:CreateLogGroup"],
        resources: [evaluationResultsLogGroupsArn],
      }),
    );
    evaluationRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
        resources: [`${evaluationResultsLogGroupsArn}:log-stream:*`],
      }),
    );

    NagSuppressions.addResourceSuppressions(
      functionRole,
      [
        {
          id: "AwsSolutions-IAM5",
          reason:
            "CloudWatch Logs requires a wildcard log-stream suffix and X-Ray write APIs do not support resource-level permissions.",
        },
      ],
      true,
    );
    NagSuppressions.addResourceSuppressions(
      gatewayRole,
      [
        {
          id: "AwsSolutions-IAM5",
          reason:
            "The Gateway is limited to GET on three API paths; each final path segment is a caller-provided fixture key.",
        },
      ],
      true,
    );
    NagSuppressions.addResourceSuppressions(
      harnessRole,
      [
        {
          id: "AwsSolutions-IAM5",
          reason:
            "JP cross-Region profiles require fixed foundation models across destination Regions; managed runtime observability also requires wildcard X-Ray/CloudWatch resources and log streams under /aws/bedrock-agentcore/runtimes only.",
        },
      ],
      true,
    );
    NagSuppressions.addResourceSuppressions(
      evaluationRole,
      [
        {
          id: "AwsSolutions-IAM5",
          reason:
            "CloudWatch Logs DescribeLogGroups and GetQueryResults do not support resource-level permissions; span access is scoped to the Harness and shared Transaction Search log groups.",
        },
      ],
      true,
    );
    NagSuppressions.addResourceSuppressions(
      api,
      [
        {
          id: "AwsSolutions-APIG3",
          reason:
            "This short-lived fixture API accepts only SigV4-authenticated calls from the least-privilege AgentCore Gateway role; WAF would add cost without a public caller.",
        },
        {
          id: "AwsSolutions-COG4",
          reason:
            "AWS_IAM is intentionally used because AgentCore Gateway signs API requests with its IAM role; Cognito is not applicable to this service-to-service API.",
        },
        {
          id: "AwsSolutions-IAM4",
          reason:
            "CDK's API Gateway account construct uses the AWS-managed service-role policy solely to deliver execution logs to CloudWatch Logs.",
        },
      ],
      true,
    );

    const dashboard = new cloudwatch.Dashboard(this, "Dashboard", {
      dashboardName: "agentcore-support-demo",
      start: "-PT3H",
      periodOverride: cloudwatch.PeriodOverride.INHERIT,
    });
    dashboard.addWidgets(
      new cloudwatch.TextWidget({
        width: 24,
        height: 1,
        markdown: "# AgentCore support agent demo",
      }),
      new cloudwatch.GraphWidget({
        width: 12,
        title: "Tools API",
        left: [toolsFunction.metricInvocations(), toolsFunction.metricErrors()],
      }),
      new cloudwatch.GraphWidget({
        width: 12,
        title: "Harness token usage by model",
        left: [
          new cloudwatch.Metric({
            namespace: "AgentCoreSupportDemo",
            metricName: "InputTokens",
            statistic: "Sum",
          }),
          new cloudwatch.Metric({
            namespace: "AgentCoreSupportDemo",
            metricName: "OutputTokens",
            statistic: "Sum",
          }),
        ],
      }),
    );

    new CfnOutput(this, "ApiId", { value: api.restApiId });
    new CfnOutput(this, "ApiUrl", { value: api.url });
    new CfnOutput(this, "HarnessName", { value: HARNESS_NAME });
    new CfnOutput(this, "HarnessRoleArn", { value: harnessRole.roleArn });
    new CfnOutput(this, "EvaluationName", { value: EVALUATION_NAME });
    new CfnOutput(this, "EvaluationRoleArn", {
      value: evaluationRole.roleArn,
    });
    new CfnOutput(this, "GatewayArn", { value: gateway.gatewayArn });
    new CfnOutput(this, "GatewayId", { value: gateway.gatewayId });
    new CfnOutput(this, "GatewayUrl", { value: gateway.gatewayUrl! });
    new CfnOutput(this, "GatewayTargetId", {
      value: gatewayTarget.attrTargetId,
    });
    new CfnOutput(this, "DashboardName", {
      value: dashboard.dashboardName,
    });
    new CfnOutput(this, "PrimaryModelId", { value: PRIMARY_MODEL });
    new CfnOutput(this, "AlternateModelId", {
      value: ALTERNATE_MODEL,
    });
  }
}
