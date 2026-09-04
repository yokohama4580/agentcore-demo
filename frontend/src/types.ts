export interface GatewayTool {
  name: string;
  method: string;
  path: string;
  intendedUse: string;
}

export interface AgentDefinition {
  modelId: string;
  temperature: number | null;
  systemPrompt: string;
  memory: { strategies?: string[]; eventExpiryDuration?: number };
  maxIterations: number | null;
  maxTokens: number | null;
  timeoutSeconds: number | null;
  slidingWindowMessages: number | null;
  gatewayTools: GatewayTool[];
  gatewayTargetName: string;
  gatewayAuth: string;
}

export interface ConsoleUrls {
  genaiObservability: string;
  agentcore: string;
  evaluations: string;
  dashboard: string;
  harnessLogs?: string;
}

export interface AppConfig {
  region: string;
  models: { primary: string; alternate: string };
  consoleUrls: ConsoleUrls;
  sessionId: string;
  harnessBaseName: string;
  evaluationName: string;
  definition: AgentDefinition;
}

export interface Agent {
  harnessName: string;
  harnessId: string;
  harnessArn: string;
  harnessVersion: string;
  status: string;
  failureReason: string | null;
  modelId: string;
  runtimeId: string;
  runtimeName: string;
  logGroup: string;
  createdAt: string | null;
}

export interface ConsoleValues {
  consoleUrl: string;
  harnessName: string;
  executionRoleArn: string;
  modelId: string;
  gatewayArn: string;
  systemPrompt: string;
  memory: string;
  maxIterations: number | null;
  maxTokens: number | null;
  timeoutSeconds: number | null;
  tag: string;
}

export interface AgentState {
  current: Agent | null;
  usable: Agent | null;
  count: number;
  baseName: string;
  suggestedName: string;
  consoleValues: ConsoleValues;
  consoleUrls: ConsoleUrls;
}

export interface Usage {
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
}

export interface ToolCall {
  toolUseId: string;
  name: string;
  input: unknown;
  status: string | null;
  content: unknown;
  startedAt: number;
  finishedAt: number | null;
}

export interface TurnMetrics {
  firstTokenMs: number | null;
  elapsedMs: number;
  usage: Usage;
}

export interface Turn {
  id: string;
  prompt: string;
  modelId: string | null;
  text: string;
  tools: ToolCall[];
  metrics: TurnMetrics | null;
  error: string | null;
  streaming: boolean;
}

export type StreamEvent =
  | { type: "text"; text: string }
  | { type: "tool_use_start"; toolUseId: string; name: string }
  | { type: "tool_use"; toolUseId: string; name: string; input: unknown }
  | {
      type: "tool_result";
      toolUseId: string;
      status: string | null;
      content: unknown;
    }
  | {
      type: "done";
      firstTokenMs: number | null;
      elapsedMs: number;
      usage: Usage;
    }
  | { type: "error"; message: string };
