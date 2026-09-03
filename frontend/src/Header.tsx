import { useState } from "react";
import type { AppConfig } from "./types";
import { modelLabel } from "./labels";

interface Props {
  config: AppConfig;
  sessionId: string;
  modelId: string | null;
  onModelChange: (modelId: string) => void;
  fault: boolean;
  onFaultChange: (fault: boolean) => void;
  showOps: boolean;
  onToggleOps: () => void;
  onNewSession: () => void;
  busy: boolean;
}

export function Header(props: Props) {
  const [settingsOpen, setSettingsOpen] = useState(false);
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

        <div className="settings">
          <button
            className={`btn icon ${props.fault ? "warn" : ""}`}
            onClick={() => setSettingsOpen((v) => !v)}
            aria-label="検証設定"
            title="検証設定"
          >
            ⚙
          </button>
          {settingsOpen && (
            <div className="settings-pop">
              <label>
                <input
                  type="checkbox"
                  checked={props.fault}
                  onChange={(e) => props.onFaultChange(e.target.checked)}
                />
                誤ルーティング規則を注入（検証用）
              </label>
              <p className="settings-note">
                呼び出し時の system prompt override で、
                処理状況の質問を配送ツールへ誘導する誤った規則を注入します。
                Harness の設定や version は変わりません。
              </p>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
