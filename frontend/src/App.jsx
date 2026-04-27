import { useCallback, useEffect, useState } from "react";
import {
  createKnowledgeBase,
  deleteKbDocument,
  deleteKnowledgeBase,
  getDocumentContent,
  getTraceStats,
  getTraces,
  listKbDocuments,
  listKnowledgeBases,
  streamChat,
  uploadKbFile,
  upsertDocs,
} from "./api";
import "./App.css";

export default function App() {
  const [sessionId, setSessionId] = useState("session-demo");
  const [kbList, setKbList] = useState([]);
  const [selectedKbId, setSelectedKbId] = useState("default");
  const [newKbName, setNewKbName] = useState("");
  const [documents, setDocuments] = useState([]);
  const [docText, setDocText] = useState("");
  const [chunkSize, setChunkSize] = useState(500);
  const [overlap, setOverlap] = useState(80);
  const [pendingFile, setPendingFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);

  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [lastMetrics, setLastMetrics] = useState(null);
  const [traceRows, setTraceRows] = useState([]);
  const [traceStats, setTraceStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [kbLoading, setKbLoading] = useState(false);
  const [fileViewer, setFileViewer] = useState({
    visible: false,
    source: "",
    content: "",
    highlight: "",
  });

  const refreshKbs = useCallback(async () => {
    const res = await listKnowledgeBases();
    setKbList(res.items || []);
  }, []);

  const refreshDocs = useCallback(async (kbId) => {
    const res = await listKbDocuments(kbId);
    setDocuments(res.documents || []);
  }, []);

  useEffect(() => {
    refreshKbs().catch((e) => console.error(e));
  }, [refreshKbs]);

  useEffect(() => {
    if (selectedKbId) {
      refreshDocs(selectedKbId).catch((e) => console.error(e));
    }
  }, [selectedKbId, refreshDocs]);

  const onCreateKb = async () => {
    if (!newKbName.trim()) return;
    setKbLoading(true);
    try {
      await createKnowledgeBase(newKbName.trim());
      setNewKbName("");
      await refreshKbs();
    } catch (e) {
      alert(e.message);
    } finally {
      setKbLoading(false);
    }
  };

  const onDeleteKb = async () => {
    if (selectedKbId === "default") {
      alert("默认知识库不可删除");
      return;
    }
    if (!window.confirm(`确定删除知识库「${selectedKbId}」？向量与文档记录将一并删除。`)) return;
    setKbLoading(true);
    try {
      await deleteKnowledgeBase(selectedKbId);
      setSelectedKbId("default");
      await refreshKbs();
    } catch (e) {
      alert(e.message);
    } finally {
      setKbLoading(false);
    }
  };

  const onDeleteDoc = async (docId) => {
    if (!window.confirm("确定删除该文档及其向量分块？")) return;
    try {
      await deleteKbDocument(selectedKbId, docId);
      await refreshDocs(selectedKbId);
    } catch (e) {
      alert(e.message);
    }
  };

  const onUpsertText = async () => {
    if (!docText.trim()) return;
    try {
      const res = await upsertDocs([{ text: docText, source: "粘贴入库" }], {
        kb_id: selectedKbId,
        chunk_size: Number(chunkSize) || 500,
        overlap: Number(overlap) || 0,
      });
      alert(`已写入 ${res.upserted_chunks} 个分块`);
      setDocText("");
      await refreshDocs(selectedKbId);
    } catch (e) {
      alert(e.message);
    }
  };

  const onUpload = async () => {
    if (!pendingFile) {
      alert("请先选择或拖入文件");
      return;
    }
    try {
      const res = await uploadKbFile(selectedKbId, pendingFile, Number(chunkSize) || 500, Number(overlap) || 0);
      alert(`上传完成，写入 ${res.upserted_chunks} 个分块`);
      setPendingFile(null);
      await refreshDocs(selectedKbId);
    } catch (e) {
      alert(e.message);
    }
  };

  const onAsk = async () => {
    if (!question.trim()) return;
    const askText = question;
    setLoading(true);
    try {
      setMessages((prev) => [
        ...prev,
        { role: "user", content: askText },
        { role: "assistant",
          content: "",
          cache_hit: false,
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
        { session_id: sessionId, question: askText, kb_id: selectedKbId },
        {
          onMeta: (meta) => {
            setMessages((prev) => {
              const next = [...prev];
              const idx = next.length - 1;
              if (idx >= 0 && next[idx].role === "assistant") {
                next[idx] = {
                  ...next[idx],
                  cache_hit: meta.cache_hit,
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
    const width = 360;
    const height = 80;
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
      <svg className="spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <polyline points={polyline} fill="none" stroke="var(--accent)" strokeWidth="2" />
      </svg>
    );
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    const f = e.dataTransfer.files?.[0];
    if (f) setPendingFile(f);
  };

  const onViewFile = async (source, highlight) => {
    try {
      const res = await getDocumentContent(selectedKbId, source);
      const content = res.content || "";
      setFileViewer({
        visible: true,
        source,
        content,
        highlight,
      });
    } catch (e) {
      alert(e.message);
    }
  };

  const closeFileViewer = () => {
    setFileViewer({
      visible: false,
      source: "",
      content: "",
      highlight: "",
    });
  };

  return (
    <div className="app-root">
      <header className="app-header">
        <div>
          <h1>Agentic Context RAG</h1>
          <p className="muted" style={{ margin: "6px 0 0" }}>
            多库检索 · 分块入库 · 流式对话
          </p>
        </div>
        <span className="tag">V1 UI</span>
      </header>

      <div className="layout">
        <div className="panel">
          <div className="panel-header">知识库</div>
          <div className="panel-body">
            <label className="field-label">选择知识库</label>
            <div className="kb-list">
              {kbList.map((k) => (
                <div
                  key={k.id}
                  className={`kb-item ${k.id === selectedKbId ? "active" : ""}`}
                  onClick={() => setSelectedKbId(k.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && setSelectedKbId(k.id)}
                >
                  <span>{k.name || k.id}</span>
                  <span className="muted" style={{ fontSize: "0.7rem" }}>
                    {k.id === "default" ? "默认" : k.id.slice(0, 8)}…
                  </span>
                </div>
              ))}
            </div>

            <div className="row">
              <div style={{ flex: 2 }}>
                <label className="field-label">新建知识库名称</label>
                <input type="text" value={newKbName} onChange={(e) => setNewKbName(e.target.value)} placeholder="例如：产品手册" />
              </div>
              <div style={{ flex: 0, minWidth: "auto" }}>
                <label className="field-label">&nbsp;</label>
                <button type="button" className="btn btn-primary" disabled={kbLoading} onClick={onCreateKb}>
                  创建
                </button>
              </div>
            </div>
            <div className="spacer" />
            <button type="button" className="btn btn-danger" disabled={selectedKbId === "default"} onClick={onDeleteKb}>
              删除当前知识库
            </button>

            <div className="spacer" />
            <label className="field-label">分块参数</label>
            <div className="row">
              <div>
                <label className="field-label">chunk_size</label>
                <input type="number" min={100} max={8000} value={chunkSize} onChange={(e) => setChunkSize(e.target.value)} />
              </div>
              <div>
                <label className="field-label">overlap</label>
                <input type="number" min={0} max={2000} value={overlap} onChange={(e) => setOverlap(e.target.value)} />
              </div>
            </div>

            <div className="spacer" />
            <label className="field-label">上传文件（UTF-8 文本，最大约 10MB）</label>
            <div
              className={`drop-zone ${dragActive ? "drag" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragActive(true);
              }}
              onDragLeave={() => setDragActive(false)}
              onDrop={onDrop}
              onClick={() => document.getElementById("file-input")?.click()}
            >
              {pendingFile ? (
                <span>已选：{pendingFile.name}</span>
              ) : (
                <span>点击或拖入 .txt / .md / .csv 等文本文件</span>
              )}
              <input
                id="file-input"
                type="file"
                style={{ display: "none" }}
                accept=".txt,.md,.csv,.json,.log,text/plain"
                onChange={(e) => setPendingFile(e.target.files?.[0] || null)}
              />
            </div>
            <button type="button" className="btn btn-primary" onClick={onUpload}>
              上传并入库
            </button>

            <div className="spacer" />
            <label className="field-label">或直接粘贴文本入库</label>
            <textarea value={docText} onChange={(e) => setDocText(e.target.value)} placeholder="粘贴知识正文…" />
            <div className="spacer" />
            <button type="button" className="btn btn-secondary" onClick={onUpsertText}>
              文本分块入库
            </button>

            <div className="spacer" />
            <label className="field-label">文档列表</label>
            <div style={{ overflowX: "auto" }}>
              <table className="doc-table">
                <thead>
                  <tr>
                    <th>标题</th>
                    <th>分块</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {documents.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="muted">
                        暂无文档，请先上传或粘贴入库
                      </td>
                    </tr>
                  ) : (
                    documents.map((d) => (
                      <tr key={d.id}>
                        <td title={d.title}>{d.title?.slice(0, 40)}{d.title?.length > 40 ? "…" : ""}</td>
                        <td>{d.chunk_count}</td>
                        <td>
                          <button type="button" className="btn btn-danger" style={{ padding: "4px 10px", fontSize: "0.75rem" }} onClick={() => onDeleteDoc(d.id)}>
                            删除
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">对话</div>
          <div className="panel-body">
            <label className="field-label">会话 ID</label>
            <input type="text" value={sessionId} onChange={(e) => setSessionId(e.target.value)} />
            <p className="muted" style={{ marginTop: 8 }}>
              当前检索知识库：<strong style={{ color: "var(--text)" }}>{kbList.find((k) => k.id === selectedKbId)?.name || selectedKbId}</strong>
            </p>

            <div className="chat-messages">
              {messages.map((m, i) => (
                <div key={i} className={`bubble ${m.role}`}>
                  {m.role === "user" ? <strong>你</strong> : <strong>助手</strong>}
                  <div style={{ marginTop: 6 }}>{m.content || (m.streaming ? "…" : "")}</div>
                  {m.role === "assistant" && !m.streaming && m.content && (
                    <div className="bubble-meta">
                      意图 {m.intent || "fact"} · 置信度 {(Number(m.confidence) || 0).toFixed(2)} · 改写 {m.rewrittenQuestion || "-"}
                      <br />
                      缓存 {String(m.cache_hit)} · 命中片段 {m.contexts?.length ?? 0}
                      {m.citations?.length > 0 && (
                        <>
                          <br />
                          引用：
                          <div className="citations">
                            {m.citations.map((c, j) => (
                              <div key={j} className="citation-item">
                                <span 
                                  className="citation-source"
                                  onClick={() => onViewFile(c.source, c.snippet)}
                                  style={{ cursor: 'pointer', textDecoration: 'underline' }}
                                >
                                  [{c.source}]
                                </span>
                                <span className="citation-snippet">{String(c.snippet || "").slice(0, 120)}</span>
                                {j < m.citations.length - 1 && <br />}
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="row" style={{ marginTop: 12 }}>
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="输入问题，回车或点发送…"
                onKeyDown={(e) => e.key === "Enter" && onAsk()}
              />
              <div style={{ flex: 0, display: "flex", gap: 8 }}>
                <button type="button" className="btn btn-primary" disabled={loading} onClick={onAsk}>
                  {loading ? "生成中…" : "发送"}
                </button>
                <button type="button" className="btn btn-secondary" onClick={onLoadTraces}>
                  性能
                </button>
              </div>
            </div>

            {lastMetrics && (
              <div className="metrics-bar">
                retrieve {lastMetrics.retrieve_ms} ms · llm {lastMetrics.llm_ms} ms · total {lastMetrics.total_ms} ms · ttft{" "}
                {lastMetrics.ttft_ms} ms
              </div>
            )}

            <div className="spacer" />
            <label className="field-label">最近性能</label>
            {traceStats && (
              <p className="muted" style={{ margin: "0 0 8px" }}>
                n={traceStats.count} · 命中率 {traceStats.cache_hit_rate} · p50 {traceStats.p50_total_ms} ms · p95 {traceStats.p95_total_ms} ms
              </p>
            )}
            {renderTotalTrend()}
            {traceRows.map((t) => (
              <div key={t.trace_id} className="muted" style={{ fontSize: "0.75rem", marginTop: 4 }}>
                {t.created_at} · cache={String(t.cache_hit)} · {t.total_ms} ms
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 文件查看模态框 */}
      {fileViewer.visible && (
        <div className="modal-overlay" onClick={closeFileViewer}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{fileViewer.source}</h3>
              <button className="modal-close" onClick={closeFileViewer}>×</button>
            </div>
            <div className="modal-body">
              <div className="file-content">
                {fileViewer.content.split('\n').map((line, i) => {
                  if (!fileViewer.highlight) {
                    return <div key={i}>{line}</div>;
                  }
                  
                  const highlightText = fileViewer.highlight.trim();
                  if (!highlightText) {
                    return <div key={i}>{line}</div>;
                  }
                  
                  const parts = line.split(new RegExp(`(${highlightText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'));
                  return (
                    <div key={i}>
                      {parts.map((part, j) => {
                        const isMatch = part.toLowerCase() === highlightText.toLowerCase();
                        return isMatch ? (
                          <span key={j} className="highlight">{part}</span>
                        ) : (
                          <span key={j}>{part}</span>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={closeFileViewer}>
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
