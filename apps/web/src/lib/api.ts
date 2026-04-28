"use client";

import { StreamEvent } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Streams anime recommendations via SSE.
 * Calls `onEvent` for each parsed event until the [DONE] sentinel.
 * Returns when the stream closes.
 */
export async function streamRecommend(
  query: string,
  topN: number,
  token: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/recommend/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ query, top_n: topN }),
    signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`API error ${res.status}: ${await res.text()}`);
  }

  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer    = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";   // keep incomplete trailing line

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6).trim();
      if (data === "[DONE]") return;
      try {
        onEvent(JSON.parse(data) as StreamEvent);
      } catch {
        // ignore malformed chunks
      }
    }
  }
}
