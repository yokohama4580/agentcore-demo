import { useCallback, useEffect, useRef, useState } from "react";
import { fetchConfig, fetchNewSession, streamChat } from "./api";
import type { AppConfig, Turn } from "./types";
import { Header } from "./Header";
import { ChatPane } from "./ChatPane";
import { OpsPane } from "./OpsPane";

let turnSeq = 0;

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string>("");
  const [modelId, setModelId] = useState<string | null>(null);
  const [fault, setFault] = useState(false);
  const [showOps, setShowOps] = useState(true);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;

  useEffect(() => {
    fetchConfig()
      .then((c) => {
        setConfig(c);
        setSessionId(c.sessionId);
        setModelId(c.models.primary);
      })
      .catch((e) => setConfigError(String(e)));
  }, []);

  const resetSession = useCallback(async () => {
    const next = await fetchNewSession();
    setSessionId(next);
    setTurns([]);
  }, []);

  const patchTurn = useCallback((id: string, patch: (turn: Turn) => Turn) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? patch(t) : t)));
  }, []);

  const send = useCallback(
    async (prompt: string) => {
      if (!sessionId || busy) return;
      const id = `turn-${++turnSeq}`;
      const turn: Turn = {
        id,
        prompt,
        modelId,
        fault,
        text: "",
        tools: [],
        metrics: null,
        error: null,
        streaming: true,
      };
      setTurns((prev) => [...prev, turn]);
      setBusy(true);
      try {
        for await (const event of streamChat({
          prompt,
          sessionId,
          modelId,
          faultInjection: fault,
        })) {
          if (event.type === "text") {
            patchTurn(id, (t) => ({ ...t, text: t.text + event.text }));
          } else if (event.type === "tool_use_start") {
            patchTurn(id, (t) => ({
              ...t,
              tools: [
                ...t.tools,
                {
                  toolUseId: event.toolUseId,
                  name: event.name,
                  input: null,
                  status: null,
                  content: null,
                  startedAt: performance.now(),
                  finishedAt: null,
                },
              ],
            }));
          } else if (event.type === "tool_use") {
            patchTurn(id, (t) => ({
              ...t,
              tools: t.tools.map((tool) =>
                tool.toolUseId === event.toolUseId
                  ? { ...tool, name: event.name, input: event.input }
                  : tool,
              ),
            }));
          } else if (event.type === "tool_result") {
            patchTurn(id, (t) => ({
              ...t,
              tools: t.tools.map((tool) =>
                tool.toolUseId === event.toolUseId
                  ? {
                      ...tool,
                      status: event.status,
                      content: event.content,
                      finishedAt: performance.now(),
                    }
                  : tool,
              ),
            }));
          } else if (event.type === "done") {
            patchTurn(id, (t) => ({
              ...t,
              streaming: false,
              metrics: {
                firstTokenMs: event.firstTokenMs,
                elapsedMs: event.elapsedMs,
                usage: event.usage ?? {},
              },
            }));
          } else if (event.type === "error") {
            patchTurn(id, (t) => ({
              ...t,
              streaming: false,
              error: event.message,
            }));
          }
        }
      } catch (e) {
        patchTurn(id, (t) => ({ ...t, streaming: false, error: String(e) }));
      } finally {
        patchTurn(id, (t) => ({ ...t, streaming: false }));
        setBusy(false);
      }
    },
    [sessionId, modelId, fault, busy, patchTurn],
  );

  if (configError) {
    return (
      <div className="boot-error">
        <h1>起動できません</h1>
        <p>{configError}</p>
        <p>scripts/ui.sh から起動してください。</p>
      </div>
    );
  }
  if (!config) {
    return <div className="boot-loading">読み込み中…</div>;
  }

  return (
    <div className={`app ${showOps ? "with-ops" : "no-ops"}`}>
      <Header
        config={config}
        sessionId={sessionId}
        modelId={modelId}
        onModelChange={setModelId}
        fault={fault}
        onFaultChange={setFault}
        showOps={showOps}
        onToggleOps={() => setShowOps((v) => !v)}
        onNewSession={resetSession}
        busy={busy}
      />
      <main className="panes">
        <ChatPane turns={turns} busy={busy} onSend={send} />
        {showOps && <OpsPane turns={turns} config={config} />}
      </main>
    </div>
  );
}
