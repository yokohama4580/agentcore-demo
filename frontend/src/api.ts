import type { Agent, AgentState, AppConfig, StreamEvent } from "./types";

export async function fetchConfig(): Promise<AppConfig> {
  const res = await fetch("/api/config");
  if (!res.ok) throw new Error(`config: HTTP ${res.status}`);
  return res.json();
}

export async function fetchAgent(refresh = false): Promise<AgentState> {
  const res = await fetch(`/api/agent${refresh ? "?refresh=1" : ""}`);
  if (!res.ok) throw new Error(`agent: HTTP ${res.status}`);
  return res.json();
}

export interface CreateAgentParams {
  harnessName: string;
  modelId: string;
  systemPrompt: string;
}

export async function createAgent(params: CreateAgentParams): Promise<Agent> {
  const res = await fetch("/api/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.detail ?? `agent: HTTP ${res.status}`);
  }
  return body as Agent;
}

export async function fetchNewSession(): Promise<string> {
  const res = await fetch("/api/session");
  if (!res.ok) throw new Error(`session: HTTP ${res.status}`);
  const body = await res.json();
  return body.sessionId;
}

export interface ChatParams {
  prompt: string;
  sessionId: string;
  modelId: string | null;
}

export async function* streamChat(
  params: ChatParams,
): AsyncGenerator<StreamEvent> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `chat: HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
      const line = chunk.trim();
      if (!line.startsWith("data:")) continue;
      yield JSON.parse(line.slice(5).trim()) as StreamEvent;
    }
  }
}
