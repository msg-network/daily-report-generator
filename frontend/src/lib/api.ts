const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export type ShiftPattern = "normal" | "late";

export type Slots = Record<string, string | null>;

export interface ParseRequest {
  date: string;
  shift_pattern: ShiftPattern;
  text: string;
}

export interface ParseResponse {
  shift_pattern: ShiftPattern;
  slots: Slots;
}

export interface GenerateRequest {
  date: string;
  shift_pattern: ShiftPattern;
  slots: Slots;
  department: string;
  name: string;
  notes: string;
}

export async function parseWorkContent(req: ParseRequest): Promise<ParseResponse> {
  const res = await fetch(`${API_BASE_URL}/api/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "不明なエラー" }));
    throw new Error(err.detail || err.error || "AI解析に失敗しました");
  }

  return res.json();
}

export async function generateDocx(req: GenerateRequest): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "不明なエラー" }));
    throw new Error(err.detail || err.error || "Word生成に失敗しました");
  }

  return res.blob();
}
