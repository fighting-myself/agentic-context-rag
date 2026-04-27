import os
import sqlite3
from datetime import datetime
from math import ceil
from typing import Any

from app.core.config import get_settings


class MemoryService:
    def __init__(self) -> None:
        self.settings = get_settings()
        os.makedirs(os.path.dirname(self.settings.sqlite_path), exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.settings.sqlite_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session_time "
                "ON messages(session_id, created_at);"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    cache_hit INTEGER NOT NULL,
                    retrieve_ms REAL NOT NULL,
                    llm_ms REAL NOT NULL,
                    total_ms REAL NOT NULL,
                    ttft_ms REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_traces_session_time "
                "ON traces(session_id, created_at);"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kb_docs_kb ON knowledge_documents(kb_id, created_at);"
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO knowledge_bases(id, name, description, created_at)
                VALUES('default', '默认知识库', '', ?)
                """,
                (datetime.utcnow().isoformat(),),
            )

    def add_message(self, session_id: str, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages(session_id, role, content, created_at) VALUES(?, ?, ?, ?)",
                (session_id, role, content, datetime.utcnow().isoformat()),
            )

    def get_recent_messages(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        size = limit or self.settings.history_limit
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, size),
            ).fetchall()
        rows.reverse()
        return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]

    def add_trace(
        self,
        trace_id: str,
        session_id: str,
        cache_hit: bool,
        retrieve_ms: float,
        llm_ms: float,
        total_ms: float,
        ttft_ms: float,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO traces(
                    trace_id, session_id, cache_hit, retrieve_ms, llm_ms, total_ms, ttft_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    session_id,
                    1 if cache_hit else 0,
                    retrieve_ms,
                    llm_ms,
                    total_ms,
                    ttft_ms,
                    datetime.utcnow().isoformat(),
                ),
            )

    def get_recent_traces(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT trace_id, session_id, cache_hit, retrieve_ms, llm_ms, total_ms, ttft_ms, created_at
                FROM traces
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [
            {
                "trace_id": r[0],
                "session_id": r[1],
                "cache_hit": bool(r[2]),
                "retrieve_ms": r[3],
                "llm_ms": r[4],
                "total_ms": r[5],
                "ttft_ms": r[6],
                "created_at": r[7],
            }
            for r in rows
        ]

    @staticmethod
    def _percentile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        index = max(0, min(len(sorted_vals) - 1, ceil(q * len(sorted_vals)) - 1))
        return float(sorted_vals[index])

    def get_trace_stats(self, session_id: str, limit: int = 100) -> dict[str, Any]:
        traces = self.get_recent_traces(session_id=session_id, limit=limit)
        if not traces:
            return {
                "count": 0,
                "cache_hit_rate": 0.0,
                "p50_total_ms": 0.0,
                "p95_total_ms": 0.0,
                "p50_ttft_ms": 0.0,
                "p95_ttft_ms": 0.0,
            }
        total_values = [float(t["total_ms"]) for t in traces]
        ttft_values = [float(t["ttft_ms"]) for t in traces]
        hit_count = sum(1 for t in traces if t["cache_hit"])
        return {
            "count": len(traces),
            "cache_hit_rate": round(hit_count / len(traces), 4),
            "p50_total_ms": round(self._percentile(total_values, 0.5), 2),
            "p95_total_ms": round(self._percentile(total_values, 0.95), 2),
            "p50_ttft_ms": round(self._percentile(ttft_values, 0.5), 2),
            "p95_ttft_ms": round(self._percentile(ttft_values, 0.95), 2),
        }

    def knowledge_base_exists(self, kb_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM knowledge_bases WHERE id = ? LIMIT 1",
                (kb_id,),
            ).fetchone()
        return row is not None

    def create_knowledge_base(self, kb_id: str, name: str, description: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO knowledge_bases(id, name, description, created_at) VALUES(?, ?, ?, ?)",
                (kb_id, name, description, datetime.utcnow().isoformat()),
            )

    def list_knowledge_bases(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, description, created_at FROM knowledge_bases ORDER BY created_at ASC"
            ).fetchall()
        return [
            {"id": r[0], "name": r[1], "description": r[2] or "", "created_at": r[3]}
            for r in rows
        ]

    def delete_knowledge_base(self, kb_id: str) -> None:
        if kb_id == "default":
            raise ValueError("cannot_delete_default_kb")
        with self._connect() as conn:
            conn.execute("DELETE FROM knowledge_documents WHERE kb_id = ?", (kb_id,))
            conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))

    def add_kb_document(
        self,
        doc_id: str,
        kb_id: str,
        title: str,
        source_type: str,
        chunk_count: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_documents(id, kb_id, title, source_type, chunk_count, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    kb_id,
                    title,
                    source_type,
                    chunk_count,
                    datetime.utcnow().isoformat(),
                ),
            )

    def list_kb_documents(self, kb_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, source_type, chunk_count, created_at
                FROM knowledge_documents
                WHERE kb_id = ?
                ORDER BY created_at DESC
                """,
                (kb_id,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "source_type": r[2],
                "chunk_count": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def delete_kb_document(self, kb_id: str, doc_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM knowledge_documents WHERE kb_id = ? AND id = ?",
                (kb_id, doc_id),
            )
