import { useCallback, useEffect, useRef, useState } from "react";
import {
  createAgent,
  fetchAgent,
  fetchConfig,
  fetchNewSession,
  streamChat,
} from "./api";
import type { AgentState, AppConfig, Turn } from "./types";
import { Header, type View } from "./Header";
import { ChatPane } from "./ChatPane";
import { OpsPane } from "./OpsPane";
import { SetupPane } from "./SetupPane";

let turnSeq = 0;

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [agent, setAgent] = useState<AgentState | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [view, setView] = useState<View>("setup");
  const [sessionId, setSessionId] = useState<string>("");
  const [modelId, setModelId] = useState<string | null>(null);
  const [showOps, setShowOps] = useState(true);
  const [turns, setTurns] = useState<Turn[]>([]);
  // 運用ビューは会話をまたいでターンを保持する（モデル比較は会話を分けて行うため）
  const [pastTurns, setPastTurns] = useState<Turn[]>([]);
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

  const refreshAgent = useCallback(async () => {
    try {
      setAgent(await fetchAgent(true));
    } catch (e) {
      setCreateError(String(e));
    }
  }, []);

  useEffect(() => {
    void refreshAgent();
  }, [refreshAgent]);

  // 作成中と未作成のあいだだけポーリングする（コンソールで作った場合も拾う）
  const status = agent?.current?.status ?? "NONE";
  useEffect(() => {
    if (status === "READY" && agent?.usable) return;
    const timer = setInterval(() => void refreshAgent(), 6000);
    return () => clearInterval(timer);
  }, [status, agent?.usable, refreshAgent]);

  const handleCreate = useCallback(
    async (params: {
      harnessName: string;
      modelId: string;
      systemPrompt: string;
    }) => {
      setCreating(true);
      setCreateError(null);
      try {
        await createAgent(params);
        await refreshAgent();
      } catch (e) {
        setCreateError(e instanceof Error ? e.message : String(e));
      } finally {
        setCreating(false);
      }
    },
    [refreshAgent],
  );

  const resetSession = useCallback(async () => {
    const next = await fetchNewSession();
    setPastTurns((prev) => [...prev, ...turnsRef.current]);
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
        sessionId,
        prompt,
        modelId,
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
        patchTurn(id, (t) => ({
          ...t,
          streaming: false,
          error: e instanceof Error ? e.message : String(e),
        }));
      } finally {
        patchTurn(id, (t) => ({ ...t, streaming: false }));
        setBusy(false);
      }
    },
    [sessionId, modelId, busy, patchTurn],
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
    <div className={`app ${view === "chat" && showOps ? "with-ops" : "no-ops"}`}>
      <Header
        config={config}
        agent={agent}
        view={view}
        onViewChange={setView}
        sessionId={sessionId}
        modelId={modelId}
        onModelChange={setModelId}
        showOps={showOps}
        onToggleOps={() => setShowOps((v) => !v)}
        onNewSession={resetSession}
        busy={busy}
      />
      {view === "setup" ? (
        <main className="setup-main">
          <SetupPane
            config={config}
            agent={agent}
            creating={creating}
            createError={createError}
            onCreate={handleCreate}
            onRefresh={() => void refreshAgent()}
            onGoChat={() => setView("chat")}
          />
        </main>
      ) : (
        <main className="panes">
          <ChatPane
            turns={[...pastTurns, ...turns]}
            busy={busy}
            onSend={send}
          />
          {showOps && (
            <OpsPane
              turns={[...pastTurns, ...turns]}
              config={config}
              agent={agent}
              sessionId={sessionId}
            />
          )}
        </main>
      )}
    </div>
  );
}
