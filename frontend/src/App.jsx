import { useState } from "react";
import { getTraceStats, getTraces, streamChat, upsertDocs } from "./api";

export default function App() {
  const [sessionId, setSessionId] = useState("session-demo");
  const [question, setQuestion] = useState("");
  const [docText, setDocText] = useState("");
  const [messages, setMessages] = useState([]);
  const [lastMetrics, setLastMetrics] = useState(null);
  const [traceRows, setTraceRows] = useState([]);
  const [traceStats, setTraceStats] = useState(null);
  const [loading, setLoading] = useState(false);

  const onAsk = async () => {
    if (!question.trim()) return;
    const askText = question;
    setLoading(true);
    try {
      setMessages((prev) => [
        ...prev,
        { role: "user", content: askText },
        {
          role: "assistant",
          content: "",
          cache: false,
          contexts: [],
          streaming: true,
          intent: "fact",
          rewrittenQuestion: askText,
          confidence: 0,
          citations: [],
        },
      ]);
      setQuestion("");

      await streamChat(
        { session_id: sessionId, question: askText },
        {
          onMeta: (meta) => {
            setMessages((prev) => {
              const next = [...prev];
              const idx = next.length - 1;
              if (idx >= 0 && next[idx].role === "assistant") {
                next[idx] = {
                  ...next[idx],
                  cache: meta.cache_hit,
                  contexts: meta.contexts || [],
                  intent: meta.intent || "fact",
                  rewrittenQuestion: meta.rewritten_question || askText,
                  confidence: Number(meta.confidence || 0),
                  citations: meta.citations || [],
                };
              }
              return next;
            });
          },
          onToken: (delta) => {
            setMessages((prev) => {
              const next = [...prev];
              const idx = next.length - 1;
              if (idx >= 0 && next[idx].role === "assistant") {
                next[idx] = {
                  ...next[idx],
                  content: `${next[idx].content}${delta}`,
                };
              }
              return next;
            });
          },
          onDone: (metrics) => {
            setLastMetrics(metrics);
            setMessages((prev) => {
              const next = [...prev];
              const idx = next.length - 1;
              if (idx >= 0 && next[idx].role === "assistant") {
                next[idx] = { ...next[idx], streaming: false };
              }
              return next;
            });
          },
        }
      );
    } catch (e) {
      alert(e.message);
    } finally {
      setLoading(false);
    }
  };

  const onUpsert = async () => {
    if (!docText.trim()) return;
    const res = await upsertDocs([{ text: docText, source: "web-ui" }]);
    alert(`入库完成，chunk 数: ${res.upserted_chunks}`);
    setDocText("");
  };

  const onLoadTraces = async () => {
    try {
      const [res, statsRes] = await Promise.all([getTraces(sessionId, 20), getTraceStats(sessionId, 100)]);
      setTraceRows(res.traces || []);
      setTraceStats(statsRes.stats || null);
    } catch (e) {
      alert(e.message);
    }
  };

  const renderTotalTrend = () => {
    if (!traceRows.length) return null;
    const points = [...traceRows].reverse().map((t) => Number(t.total_ms || 0));
    const width = 420;
    const height = 100;
    const maxVal = Math.max(...points, 1);
    const minVal = Math.min(...points, 0);
    const spread = Math.max(maxVal - minVal, 1);
    const polyline = points
      .map((v, i) => {
        const x = (i / Math.max(points.length - 1, 1)) * width;
        const y = height - ((v - minVal) / spread) * height;
        return `${x},${y}`;
      })
      .join(" ");
    return (
      <svg width={width} height={height} style={{ border: "1px solid #ddd", background: "#fafafa" }}>
        <polyline points={polyline} fill="none" stroke="#2f80ed" strokeWidth="2" />
      </svg>
    );
  };

  return (
    <div style={{ maxWidth: 900, margin: "20px auto", fontFamily: "Arial, sans-serif" }}>
      <h2>Agentic Context RAG V1</h2>
      <div style={{ marginBottom: 12 }}>
        <label>会话 ID: </label>
        <input value={sessionId} onChange={(e) => setSessionId(e.target.value)} />
      </div>

      <div style={{ marginBottom: 20 }}>
        <h4>知识库写入</h4>
        <textarea
          rows={4}
          style={{ width: "100%" }}
          value={docText}
          onChange={(e) => setDocText(e.target.value)}
          placeholder="输入知识文本后点击入库"
        />
        <button onClick={onUpsert}>入库</button>
      </div>

      <div style={{ marginBottom: 20 }}>
        <h4>对话</h4>
        <input
          style={{ width: "80%" }}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="请输入问题"
        />
        <button disabled={loading} onClick={onAsk}>
          {loading ? "回答中..." : "发送"}
        </button>
        <button onClick={onLoadTraces} style={{ marginLeft: 8 }}>
          查看性能
        </button>
        {lastMetrics && (
          <div style={{ marginTop: 8, color: "#444", fontSize: 13 }}>
            retrieve={lastMetrics.retrieve_ms}ms | llm={lastMetrics.llm_ms}ms | total=
            {lastMetrics.total_ms}ms | ttft={lastMetrics.ttft_ms}ms
          </div>
        )}
      </div>

      <div>
        {messages.map((m, i) => (
          <div key={i} style={{ borderBottom: "1px solid #ddd", padding: "8px 0" }}>
            <b>{m.role}:</b> {m.content}
            {m.role === "assistant" && (
              <div style={{ marginTop: 4, color: "#666", fontSize: 12 }}>
                cache_hit={String(m.cache)} | contexts={m.contexts.length} | streaming=
                {String(Boolean(m.streaming))}
                <br />
                intent={m.intent || "fact"} | confidence={Number(m.confidence || 0).toFixed(2)}
                <br />
                rewritten={m.rewrittenQuestion || "-"}
                {!!(m.citations && m.citations.length) && (
                  <>
                    <br />
                    引用:{" "}
                    {m.citations
                      .map((c) => `[${c.source}] ${String(c.snippet || "").slice(0, 30)}...`)
                      .join(" | ")}
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 20 }}>
        <h4>最近性能记录</h4>
        {traceStats && (
          <div style={{ fontSize: 12, color: "#444", marginBottom: 8 }}>
            count={traceStats.count} | hit_rate={traceStats.cache_hit_rate} | p50_total=
            {traceStats.p50_total_ms}ms | p95_total={traceStats.p95_total_ms}ms | p50_ttft=
            {traceStats.p50_ttft_ms}ms | p95_ttft={traceStats.p95_ttft_ms}ms
          </div>
        )}
        <div style={{ marginBottom: 8 }}>{renderTotalTrend()}</div>
        {traceRows.map((t) => (
          <div key={t.trace_id} style={{ fontSize: 12, color: "#444", marginBottom: 4 }}>
            {t.created_at} | cache={String(t.cache_hit)} | total={t.total_ms}ms | ttft={t.ttft_ms}ms
          </div>
        ))}
      </div>
    </div>
  );
}
