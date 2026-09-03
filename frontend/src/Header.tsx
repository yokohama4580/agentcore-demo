import type { AppConfig } from "./types";
import { modelLabel } from "./labels";

interface Props {
  config: AppConfig;
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

  return (
    <header className="header">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <span className="brand-name">Asagao</span>
        <span className="brand-sub">注文管理クラウド</span>
      </div>

      <div className="header-controls">
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
      </div>
    </header>
  );
}
