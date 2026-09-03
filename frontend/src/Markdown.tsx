import { Fragment, type ReactNode } from "react";

/** 依存を増やさない最小の Markdown 描画（太字と箇条書きのみ）。 */

function renderInline(text: string): ReactNode[] {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : <Fragment key={i}>{part}</Fragment>,
  );
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const nodes: ReactNode[] = [];
  let bullets: string[] = [];

  const flushBullets = (key: string) => {
    if (bullets.length === 0) return;
    nodes.push(
      <ul key={key}>
        {bullets.map((item, i) => (
          <li key={i}>{renderInline(item)}</li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  lines.forEach((line, i) => {
    const bullet = line.match(/^\s*[-・]\s+(.*)$/);
    if (bullet) {
      bullets.push(bullet[1]);
      return;
    }
    flushBullets(`ul-${i}`);
    nodes.push(<Fragment key={`ln-${i}`}>{renderInline(line)}{"\n"}</Fragment>);
  });
  flushBullets("ul-end");

  return <>{nodes}</>;
}
