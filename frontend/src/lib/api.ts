export type StreamEvent =
  | { type: "reasoning" | "content" | "error"; delta: string }
  | { type: "done" };

export type TaskRequest = {
  thread_id: string;
  message: string;
  persona_block: string;
  human_block: string;
};

export type Health = {
  status: string;
  model: string;
  llm_configured: boolean;
  persistence: string;
  cache: string;
};

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/api/backend/health", { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Health check failed (${response.status})`);
  return response.json();
}

/** POST a task and yield events as the agent produces them. */
export async function* streamTask(
  body: TaskRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch("/api/backend/run_task/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `Request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("");
      if (data) yield JSON.parse(data) as StreamEvent;
    }
  }
}
