import { useEffect, useState } from "react";
import { fetchNewSession, streamChat } from "./api";
import type { AgentState, AppConfig } from "./types";
import { maskAccountId, modelLabel, shortToolName, toolLabel } from "./labels";

const TEST_PROMPT = "注文 A-100 はいま何が起きていますか？";

interface Props {
  config: AppConfig;
  agent: AgentState | null;
  creating: boolean;
  createError: string | null;
  onCreate: (params: {
    harnessName: string;
    modelId: string;
    systemPrompt: string;
  }) => void;
  onRefresh: () => void;
  onGoChat: () => void;
}

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="paste-row">
      <span className="paste-label">{label}</span>
      <code className="paste-value">{maskAccountId(value)}</code>
      <button
        className="btn small"
        onClick={() => {
          navigator.clipboard?.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "コピーしました" : "コピー"}
      </button>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  const label =
    status === "READY"
      ? "READY（呼び出せます）"
      : status === "CREATING"
        ? "CREATING（作成中）"
        : status;
  return <span className={`agent-chip ${status.toLowerCase()}`}>{label}</span>;
}

export function SetupPane(props: Props) {
  const { config, agent } = props;
  const definition = config.definition;
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState(definition.modelId);
  const [systemPrompt, setSystemPrompt] = useState(definition.systemPrompt);
  const [testBusy, setTestBusy] = useState(false);
  const [testText, setTestText] = useState("");
  const [testTools, setTestTools] = useState<string[]>([]);
  const [testError, setTestError] = useState<string | null>(null);

  useEffect(() => {
    if (agent && !name) setName(agent.suggestedName);
  }, [agent, name]);

  const current = agent?.current ?? null;
  const usable = agent?.usable ?? null;
  const creating = props.creating || current?.status === "CREATING";

  const runTest = async () => {
    setTestBusy(true);
    setTestText("");
    setTestTools([]);
    setTestError(null);
    try {
      const sessionId = await fetchNewSession();
      for await (const event of streamChat({
        prompt: TEST_PROMPT,
        sessionId,
        modelId: null,
      })) {
        if (event.type === "text") {
          setTestText((prev) => prev + event.text);
        } else if (event.type === "tool_use_start") {
          setTestTools((prev) => [...prev, event.name]);
        } else if (event.type === "error") {
          setTestError(event.message);
        }
      }
    } catch (error) {
      setTestError(String(error));
    } finally {
      setTestBusy(false);
    }
  };

  return (
    <div className="setup">
      <section className="card">
        <h2>① エージェントを宣言する</h2>
        <p className="card-lead">
          書くのはこの設定だけです。オーケストレーションのコード・コンテナ・
          ツール実行の処理は用意しません。
        </p>

        <label className="field">
          <span>名前</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            spellCheck={false}
          />
        </label>

        <label className="field">
          <span>モデル</span>
          <select
            value={modelId}
            onChange={(event) => setModelId(event.target.value)}
          >
            {[config.models.primary, config.models.alternate].map((id) => (
              <option key={id} value={id}>
                {modelLabel(id)}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>指示（system prompt）</span>
          <textarea
            rows={4}
            value={systemPrompt}
            onChange={(event) => setSystemPrompt(event.target.value)}
          />
        </label>

        <div className="field-block">
          <span className="field-title">
            ツール（AgentCore Gateway 経由・{definition.gatewayAuth}）
          </span>
          <ul className="tool-list">
            {definition.gatewayTools.map((tool) => (
              <li key={tool.name}>
                <code>{shortToolName(tool.name)}</code>
                <span className="tool-jp">{toolLabel(tool.name)}</span>
                <span className="tool-api">
                  {tool.method} {tool.path}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="field-block">
          <span className="field-title">その他の宣言</span>
          <ul className="spec-list">
            <li>
              メモリ: {definition.memory.strategies?.join(" + ")}（保持{" "}
              {definition.memory.eventExpiryDuration} 日）
            </li>
            <li>
              実行上限: 最大 {definition.maxIterations} 反復 / 応答{" "}
              {definition.maxTokens} トークン / {definition.timeoutSeconds} 秒
            </li>
            <li>
              コンテキスト: 直近 {definition.slidingWindowMessages}{" "}
              メッセージのスライディングウィンドウ
            </li>
            <li>
              実行環境: セッションごとの microVM（PUBLIC ネットワーク）
            </li>
          </ul>
        </div>

        <div className="card-actions">
          <button
            className="btn primary"
            disabled={creating || !name}
            onClick={() =>
              props.onCreate({ harnessName: name, modelId, systemPrompt })
            }
          >
            {creating ? "作成中…" : "この設定でエージェントを作成"}
          </button>
          <button className="btn" onClick={props.onRefresh}>
            最新の状態を取得
          </button>
        </div>
        {props.createError && (
          <p className="card-error">⚠ {props.createError}</p>
        )}
      </section>

      <section className="card">
        <h2>② 作成の状態</h2>
        {current === null && (
          <p className="card-lead">
            まだエージェントはありません。左のボタン、または AWS
            コンソールのフォームから作成してください（どちらで作っても
            この画面が自動で見つけます）。
          </p>
        )}
        {current && (
          <div className="agent-status">
            <div className="agent-status-head">
              <StatusChip status={current.status} />
              <code>{current.harnessId}</code>
            </div>
            <ul className="spec-list">
              <li>名前: {current.harnessName}</li>
              <li>バージョン: v{current.harnessVersion}</li>
              <li>モデル: {modelLabel(current.modelId)}</li>
              <li>実行環境: {current.runtimeId || "作成中"}</li>
              {current.createdAt && (
                <li>作成: {new Date(current.createdAt).toLocaleString()}</li>
              )}
              {current.failureReason && (
                <li className="card-error">理由: {current.failureReason}</li>
              )}
            </ul>
            {current.status === "CREATING" && (
              <p className="card-note">
                READY になるまで数分かかります（この画面は自動で更新します）。
              </p>
            )}
          </div>
        )}
        {usable && current && usable.harnessId !== current.harnessId && (
          <p className="card-note">
            いま呼び出せるのは <code>{usable.harnessId}</code> です（作成が
            完了したら自動で切り替わります）。
          </p>
        )}

        {usable && (
          <div className="agent-test">
            <h3>その場でテストする</h3>
            <p className="card-note">質問: {TEST_PROMPT}</p>
            <div className="card-actions">
              <button
                className="btn primary"
                onClick={runTest}
                disabled={testBusy}
              >
                {testBusy ? "実行中…" : "テスト実行"}
              </button>
              <button className="btn" onClick={props.onGoChat}>
                自社製品の画面へ →
              </button>
            </div>
            {testTools.length > 0 && (
              <p className="card-note">
                呼ばれたツール:{" "}
                {testTools.map((tool) => shortToolName(tool)).join(" → ")}
              </p>
            )}
            {testText && <div className="test-answer">{testText}</div>}
            {testError && <p className="card-error">⚠ {testError}</p>}
          </div>
        )}
      </section>

      <section className="card">
        <h2>③ AWS コンソールで作る場合</h2>
        <p className="card-lead">
          同じ内容をコンソールのフォームに入れても結果は同じです。貼り付ける値:
        </p>
        {agent && (
          <div className="paste-list">
            <CopyRow label="名前" value={agent.consoleValues.harnessName} />
            <CopyRow
              label="実行ロール"
              value={agent.consoleValues.executionRoleArn}
            />
            <CopyRow label="モデル" value={agent.consoleValues.modelId} />
            <CopyRow label="Gateway" value={agent.consoleValues.gatewayArn} />
            <CopyRow
              label="system prompt"
              value={agent.consoleValues.systemPrompt}
            />
            <CopyRow label="タグ" value={agent.consoleValues.tag} />
            <p className="card-note">
              メモリ: {agent.consoleValues.memory} ／ 実行上限:{" "}
              {agent.consoleValues.maxIterations} 反復 ·{" "}
              {agent.consoleValues.maxTokens} トークン ·{" "}
              {agent.consoleValues.timeoutSeconds} 秒
            </p>
            <p className="card-note">
              タグ <code>{agent.consoleValues.tag}</code>{" "}
              を付け忘れると後片付けの対象から漏れます。
            </p>
            <a
              className="btn"
              href={agent.consoleValues.consoleUrl}
              target="_blank"
              rel="noreferrer"
            >
              AgentCore コンソールを開く ↗
            </a>
          </div>
        )}
      </section>
    </div>
  );
}
