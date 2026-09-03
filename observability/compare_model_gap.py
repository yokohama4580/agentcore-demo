#!/usr/bin/env python3
"""Step 3: 同じ質問をモデルだけ替えて新規セッションで投げ、答えの差を並べる。

質問は「注文の商品 → SKU → 在庫」の 2 段のツール呼び出しが要るもの。
どちらの答えが正しいかは画面からは判定できない、というのが見どころ。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from invoke_harness import invoke, new_session_id

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".demo-state"
PROMPT = "注文 A-100 の商品は、いま在庫がありますか？"


def short_tools(result: dict) -> str:
    names = []
    for tool in result["toolUses"]:
        name = tool.get("name", "")
        names.append(name.split("___")[-1] or name)
    return " -> ".join(names) if names else "（ツール呼び出しなし）"


def main() -> None:
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    harness_arn = os.environ["HARNESS_ARN"]
    labels = {
        "model-gap-primary": os.environ["PRIMARY_MODEL_ID"],
        "model-gap-alternate": os.environ["ALTERNATE_MODEL_ID"],
    }
    results: dict[str, dict] = {}

    print(f"質問（両モデル共通・毎回新規セッション）: {PROMPT}\n")
    for label, model_id in labels.items():
        session_id = new_session_id()
        print(f"--- model={model_id}")
        result = invoke(
            prompt=PROMPT,
            harness_arn=harness_arn,
            profile=profile,
            region=region,
            session_id=session_id,
            actor_id=f"{label}-{session_id}",
            scenario=label,
            model_id=model_id,
            system_prompt=None,
            emit=False,
        )
        results[label] = result
        print(f"tools:  {short_tools(result)}")
        print(f"answer: {result['responseText'].strip()}")
        print(
            f"latency: total {result.get('elapsedMs')}ms / "
            f"tokens {result.get('usage', {}).get('totalTokens', 0)}\n"
        )
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / f"latest-{label}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print("同じエージェント・同じ質問でも、モデルによって答えが変わりました。")
    print("どちらが正しいかはこの画面からは分かりません。次の Step 4 で中身（トレース）を見ます。")


if __name__ == "__main__":
    main()
