import { useEffect, useRef } from "react";
import type { AppConfig, ToolCall, Turn } from "./types";
import { formatJson, modelLabel, shortToolName, toolLabel } from "./labels";

interface Props {
  turns: Turn[];
  config: AppConfig;
}

function ToolCard({ tool }: { tool: ToolCall }) {
  const running = tool.finishedAt === null;
  const durationMs =
    tool.finishedAt !== null
      ? Math.round(tool.finishedAt - tool.startedAt)
      : null;
  return (
    <div className={`ops-tool ${running ? "running" : ""}`}>
      <div className="ops-tool-head">
        <span className="ops-tool-badge">TOOL</span>
        <span className="ops-tool-label">{toolLabel(tool.name)}</span>
        <code className="ops-tool-name">{shortToolName(tool.name)}</code>
        {durationMs !== null ? (
          <span className="ops-tool-ms">{durationMs} ms</span>
        ) : (
          <span className="ops-tool-ms running">実行中…</span>
        )}
      </div>
      {tool.input != null && (
        <div className="ops-kv">
          <span className="ops-kv-key">引数</span>
          <pre>{formatJson(tool.input)}</pre>
        </div>
      )}
      {tool.content != null && (
        <div className="ops-kv">
          <span className="ops-kv-key">
            結果{tool.status ? `（${tool.status}）` : ""}
          </span>
          <pre>{formatJson(tool.content)}</pre>
        </div>
      )}
    </div>
  );
}

function TurnBlock({ turn, index }: { turn: Turn; index: number }) {
  return (
    <div className="ops-turn">
      <div className="ops-turn-head">
        <span className="ops-turn-no">#{index + 1}</span>
        <span className="ops-turn-prompt">{turn.prompt}</span>
      </div>
      <div className="ops-turn-meta">
        <span className="ops-model">
          {turn.modelId ? modelLabel(turn.modelId) : "harness 既定"}
        </span>
      </div>
      {turn.tools.map((tool) => (
        <ToolCard key={tool.toolUseId} tool={tool} />
      ))}
      {turn.error && <div className="ops-error">⚠ {turn.error}</div>}
      {turn.metrics && (
        <div className="ops-metrics">
          <span>
            初回応答{" "}
            <strong>
              {turn.metrics.firstTokenMs != null
                ? `${turn.metrics.firstTokenMs} ms`
                : "—"}
            </strong>
          </span>
          <span>
            合計 <strong>{turn.metrics.elapsedMs} ms</strong>
          </span>
          <span>
            トークン{" "}
            <strong>
              {turn.metrics.usage.inputTokens ?? 0} in /{" "}
              {turn.metrics.usage.outputTokens ?? 0} out
            </strong>
          </span>
        </div>
      )}
    </div>
  );
}

function CompareTable({ turns }: { turns: Turn[] }) {
  const finished = turns.filter((t) => t.metrics);
  if (finished.length < 2) return null;
  return (
    <div className="ops-compare">
      <h3>ターン比較</h3>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>モデル</th>
            <th>ツール</th>
            <th>合計</th>
            <th>in/out</th>
          </tr>
        </thead>
        <tbody>
          {finished.map((t) => (
            <tr key={t.id}>
              <td>{turns.indexOf(t) + 1}</td>
              <td>{t.modelId ? modelLabel(t.modelId) : "既定"}</td>
              <td>
                {t.tools.map((tool) => shortToolName(tool.name)).join(", ") ||
                  "—"}
              </td>
              <td>{t.metrics!.elapsedMs} ms</td>
              <td>
                {t.metrics!.usage.inputTokens ?? 0}/
                {t.metrics!.usage.outputTokens ?? 0}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OpsPane({ turns, config }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  return (
    <aside className="ops-pane" aria-label="運用ビュー">
      <div className="ops-head">
        <h2>運用ビュー</h2>
        <span className="ops-head-sub">エージェントの裏側</span>
      </div>
      <div className="ops-scroll" ref={scrollRef}>
        {turns.length === 0 && (
          <p className="ops-empty">
            会話を始めると、モデル・ツール呼び出し・レイテンシ・トークン数が
            ここに流れます。左の画面（顧客に見えるもの）と、ここ（運用者が
            見るべきもの）の差が今日の主題です。
          </p>
        )}
        {turns.map((turn, i) => (
          <TurnBlock key={turn.id} turn={turn} index={i} />
        ))}
        <CompareTable turns={turns} />
      </div>
      <div className="ops-footer">
        <span className="ops-harness">
          harness {config.harnessId} · v{config.harnessVersion}
        </span>
        <div className="ops-links">
          <a
            href={config.consoleUrls.genaiObservability}
            target="_blank"
            rel="noreferrer"
          >
            GenAI Observability ↗
          </a>
          <a
            href={config.consoleUrls.evaluations}
            target="_blank"
            rel="noreferrer"
          >
            Evaluations ↗
          </a>
        </div>
      </div>
    </aside>
  );
}
