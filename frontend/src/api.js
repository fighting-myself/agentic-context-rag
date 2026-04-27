const API_BASE = import.meta.env.VITE_API_BASE || "/api/v1";

export async function sendChat(payload) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`chat failed: ${res.status}`);
  }
  return await res.json();
}

export async function upsertDocs(docs) {
  const res = await fetch(`${API_BASE}/knowledge/upsert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ docs }),
  });
  if (!res.ok) {
    throw new Error(`upsert failed: ${res.status}`);
  }
  return await res.json();
}

export async function streamChat(payload, handlers = {}) {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.body) {
    throw new Error(`stream failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let splitIndex = buffer.indexOf("\n\n");
    while (splitIndex !== -1) {
      const rawEvent = buffer.slice(0, splitIndex).trim();
      buffer = buffer.slice(splitIndex + 2);
      if (rawEvent.startsWith("data: ")) {
        const data = JSON.parse(rawEvent.slice(6));
        if (data.type === "meta" && handlers.onMeta) handlers.onMeta(data);
        if (data.type === "token" && handlers.onToken) handlers.onToken(data.delta || "");
        if (data.type === "done" && handlers.onDone) handlers.onDone(data.metrics || {});
      }
      splitIndex = buffer.indexOf("\n\n");
    }
  }
}

export async function getTraces(sessionId, limit = 20) {
  const res = await fetch(`${API_BASE}/traces/${encodeURIComponent(sessionId)}?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`traces failed: ${res.status}`);
  }
  return await res.json();
}

export async function getTraceStats(sessionId, limit = 100) {
  const res = await fetch(`${API_BASE}/traces/${encodeURIComponent(sessionId)}/stats?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`trace stats failed: ${res.status}`);
  }
  return await res.json();
}
