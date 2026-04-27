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

export async function upsertDocs(docs, options = {}) {
  const { kb_id = "default", chunk_size = 500, overlap = 80 } = options;
  const res = await fetch(`${API_BASE}/knowledge/upsert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kb_id, docs, chunk_size, overlap }),
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

export async function listKnowledgeBases() {
  const res = await fetch(`${API_BASE}/knowledge-bases`);
  if (!res.ok) throw new Error(`list kb failed: ${res.status}`);
  return await res.json();
}

export async function createKnowledgeBase(name, description = "") {
  const res = await fetch(`${API_BASE}/knowledge-bases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) throw new Error(`create kb failed: ${res.status}`);
  return await res.json();
}

export async function deleteKnowledgeBase(kbId) {
  const res = await fetch(`${API_BASE}/knowledge-bases/${encodeURIComponent(kbId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`delete kb failed: ${res.status}`);
  return await res.json();
}

export async function listKbDocuments(kbId) {
  const res = await fetch(`${API_BASE}/knowledge-bases/${encodeURIComponent(kbId)}/documents`);
  if (!res.ok) throw new Error(`list docs failed: ${res.status}`);
  return await res.json();
}

export async function deleteKbDocument(kbId, docId) {
  const res = await fetch(
    `${API_BASE}/knowledge-bases/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(docId)}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error(`delete doc failed: ${res.status}`);
  return await res.json();
}

export async function uploadKbFile(kbId, file, chunkSize, overlap) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("chunk_size", String(chunkSize));
  fd.append("overlap", String(overlap));
  const res = await fetch(`${API_BASE}/knowledge-bases/${encodeURIComponent(kbId)}/upload`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) throw new Error(`upload failed: ${res.status}`);
  return await res.json();
}
