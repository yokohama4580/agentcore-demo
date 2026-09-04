import { useEffect, useRef, useState } from "react";
import type { Turn } from "./types";
import { Markdown } from "./Markdown";

const SUGGESTIONS = [
  "注文 A-100 はいま何が起きていますか？",
  "その注文の支払いは済んでいますか？",
  "注文 A-100 の配送はいつ届く予定ですか？",
  "注文 A-100 の商品は、いま在庫がありますか？",
];

interface Props {
  turns: Turn[];
  busy: boolean;
  onSend: (prompt: string) => void;
}

export function ChatPane({ turns, busy, onSend }: Props) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const submit = (text: string) => {
    const prompt = text.trim();
    if (!prompt || busy) return;
    setDraft("");
    onSend(prompt);
  };

  return (
    <section className="chat-pane" aria-label="サポートチャット">
      <div className="chat-scroll" ref={scrollRef}>
        {turns.length === 0 && (
          <div className="chat-empty">
            <h2>AI アシスタント</h2>
            <p>注文・在庫・配送について質問できます。</p>
          </div>
        )}
        {turns.map((turn, i) => (
          <div key={turn.id}>
            {i > 0 && turns[i - 1].sessionId !== turn.sessionId && (
              <div className="chat-session-break">新しい会話</div>
            )}
            <div className="exchange">
            <div className="bubble user">{turn.prompt}</div>
            <div className={`bubble assistant ${turn.streaming ? "streaming" : ""}`}>
              {turn.tools.some((t) => t.finishedAt === null) && (
                <span className="working">確認しています…</span>
              )}
              <Markdown text={turn.text} />
              {turn.streaming && <span className="caret" aria-hidden="true" />}
              {turn.error && <span className="chat-error">⚠ {turn.error}</span>}
            </div>
            </div>
          </div>
        ))}
      </div>

      <div className="chat-input-area">
        <div className="suggestions">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              className="chip"
              disabled={busy}
              onClick={() => submit(s)}
            >
              {s}
            </button>
          ))}
        </div>
        <form
          className="chat-form"
          onSubmit={(e) => {
            e.preventDefault();
            submit(draft);
          }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="質問を入力…"
            disabled={busy}
          />
          <button type="submit" className="send" disabled={busy || !draft.trim()}>
            送信
          </button>
        </form>
      </div>
    </section>
  );
}
