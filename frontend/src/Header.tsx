import type { AgentState, AppConfig } from "./types";
import { modelLabel } from "./labels";

export type View = "setup" | "chat";

interface Props {
  config: AppConfig;
  agent: AgentState | null;
  view: View;
  onViewChange: (view: View) => void;
  sessionId: string;
  modelId: string | null;
  onModelChange: (modelId: string) => void;
  showOps: boolean;
  onToggleOps: () => void;
  onNewSession: () => void;
  busy: boolean;
}

export function Header(props: Props) {
  const { models } = props.config;
  const choices = [models.primary, models.alternate];
  const agent = props.agent?.usable ?? props.agent?.current ?? null;

  return (
    <header className="header">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <span className="brand-name">Asagao</span>
        <span className="brand-sub">注文管理クラウド</span>
      </div>

      <div className="segmented views" role="group" aria-label="画面">
        <button
          className={`segment ${props.view === "setup" ? "active" : ""}`}
          onClick={() => props.onViewChange("setup")}
        >
          エージェント設定
        </button>
        <button
          className={`segment ${props.view === "chat" ? "active" : ""}`}
          onClick={() => props.onViewChange("chat")}
        >
          AI アシスタント
        </button>
      </div>

      <div className="header-controls">
        {props.view === "chat" && (
          <>
            <div className="segmented" role="group" aria-label="モデル">
              {choices.map((m) => (
                <button
                  key={m}
                  className={`segment ${props.modelId === m ? "active" : ""}`}
                  onClick={() => props.onModelChange(m)}
                  disabled={props.busy}
                >
                  {modelLabel(m)}
                </button>
              ))}
            </div>

            <span className="session-chip" title={props.sessionId}>
              session {props.sessionId.slice(0, 8)}
            </span>

            <button
              className="btn"
              onClick={props.onNewSession}
              disabled={props.busy}
            >
              新しい会話
            </button>

            <button className="btn" onClick={props.onToggleOps}>
              {props.showOps ? "裏側を隠す" : "裏側を表示"}
            </button>
          </>
        )}
        {props.view === "setup" && (
          <span
            className={`agent-chip ${(agent?.status ?? "none").toLowerCase()}`}
            title={agent?.harnessArn ?? ""}
          >
            {agent ? `${agent.harnessName} · ${agent.status}` : "エージェント未作成"}
          </span>
        )}
      </div>
    </header>
  );
}
