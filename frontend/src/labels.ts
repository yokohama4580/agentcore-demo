export function shortToolName(name: string): string {
  const parts = name.split("___");
  return parts[parts.length - 1];
}

const TOOL_LABELS: Record<string, string> = {
  inspect_order_lifecycle: "注文ライフサイクル照会",
  lookup_inventory: "在庫照会",
  lookup_order_shipment_status: "配送状況照会",
};

export function toolLabel(name: string): string {
  const short = shortToolName(name);
  return TOOL_LABELS[short] ?? short;
}

export function modelLabel(modelId: string): string {
  if (modelId.includes("claude-haiku-4-5")) return "Claude Haiku 4.5";
  if (modelId.includes("nova-2-lite")) return "Nova 2 Lite";
  const tail = modelId.split(".").pop() ?? modelId;
  return tail.replace(/-v\d.*$/, "");
}

/** 画面に出す ARN から AWS アカウント ID を隠す（コピーされる値は実物のまま）。 */
export function maskAccountId(text: string): string {
  return text.replace(/\d{12}/g, "•".repeat(12));
}

export function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
