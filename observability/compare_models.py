#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".demo-state"


def main() -> None:
    results = []
    for label in ("model-primary", "model-alternate"):
        path = STATE_DIR / f"latest-{label}.json"
        results.append(json.loads(path.read_text(encoding="utf-8")))

    print(
        f"{'model':58} {'first':>8} {'total':>8} {'tokens':>8}\n"
        + "-" * 88
    )
    for result in results:
        print(
            f"{result['modelId'][:58]:58} "
            f"{str(result.get('firstTokenMs')) + 'ms':>8} "
            f"{str(result.get('elapsedMs')) + 'ms':>8} "
            f"{result.get('usage', {}).get('totalTokens', 0):>8}"
        )


if __name__ == "__main__":
    main()
