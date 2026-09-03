export interface AppConfig {
  harnessId: string;
  harnessVersion: string;
  region: string;
  models: { primary: string; alternate: string };
  consoleUrls: {
    genaiObservability: string;
    evaluations: string;
    harnessLogs: string;
  };
  sessionId: string;
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
  fault: boolean;
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
