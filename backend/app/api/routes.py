import json
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, Header, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.exceptions import AppError
from app.core.logging import new_trace_id
from app.services.cache_service import CacheService
from app.services.chat_service import ChatService
from app.services.kb_service import KnowledgeBaseService
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService

router = APIRouter()

memory_service = MemoryService()
kb_service = KnowledgeBaseService()
kb_service.ensure_collection("default")
retrieval_service = RetrievalService(kb_service=kb_service)
cache_service = CacheService()
chat_service = ChatService(
    memory_service=memory_service,
    retrieval_service=retrieval_service,
    cache_service=cache_service,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    kb_id: str = Field(default="default", min_length=1)


class KnowledgeDoc(BaseModel):
    text: str = Field(min_length=1)
    source: str = "manual"


class KnowledgeUpsertRequest(BaseModel):
    kb_id: str = Field(default="default", min_length=1)
    docs: list[KnowledgeDoc]
    chunk_size: int = Field(default=500, ge=100, le=8000)
    overlap: int = Field(default=80, ge=0, le=2000)


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)


def _require_kb(kb_id: str) -> None:
    if not memory_service.knowledge_base_exists(kb_id):
        raise AppError("knowledge_base_not_found", status_code=404)


@router.post("/chat")
def chat(payload: ChatRequest, x_trace_id: str | None = Header(default=None)) -> dict[str, Any]:
    _require_kb(payload.kb_id)
    trace_id = x_trace_id or new_trace_id()
    result = chat_service.ask(
        session_id=payload.session_id,
        question=payload.question,
        trace_id=trace_id,
        kb_id=payload.kb_id,
    )
    result["trace_id"] = trace_id
    return result


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, x_trace_id: str | None = Header(default=None)):
    _require_kb(payload.kb_id)
    trace_id = x_trace_id or new_trace_id()

    async def event_gen():
        async for event in chat_service.stream_ask(
            session_id=payload.session_id,
            question=payload.question,
            trace_id=trace_id,
            kb_id=payload.kb_id,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/knowledge/upsert")
def knowledge_upsert(payload: KnowledgeUpsertRequest) -> dict[str, Any]:
    _require_kb(payload.kb_id)
    doc_id = uuid.uuid4().hex
    total = kb_service.upsert_documents(
        payload.kb_id,
        [d.model_dump() for d in payload.docs],
        chunk_size=payload.chunk_size,
        overlap=payload.overlap,
        doc_id=doc_id,
    )
    if total > 0:
        memory_service.add_kb_document(doc_id, payload.kb_id, "文本入库", "paste", total)
    return {"upserted_chunks": total, "kb_id": payload.kb_id, "doc_id": doc_id if total > 0 else None}


@router.post("/knowledge-bases")
def create_knowledge_base(payload: CreateKnowledgeBaseRequest) -> dict[str, Any]:
    kb_id = uuid.uuid4().hex
    memory_service.create_knowledge_base(kb_id, payload.name.strip(), payload.description.strip())
    kb_service.ensure_collection(kb_id)
    return {"id": kb_id, "name": payload.name, "description": payload.description}


@router.get("/knowledge-bases")
def list_knowledge_bases() -> dict[str, Any]:
    return {"items": memory_service.list_knowledge_bases()}


@router.delete("/knowledge-bases/{kb_id}")
def delete_knowledge_base(kb_id: str) -> dict[str, Any]:
    if kb_id == "default":
        raise AppError("cannot_delete_default_kb", status_code=400)
    _require_kb(kb_id)
    memory_service.delete_knowledge_base(kb_id)
    kb_service.delete_knowledge_base_vectors(kb_id)
    return {"deleted": kb_id}


@router.get("/knowledge-bases/{kb_id}/documents")
def list_kb_documents(kb_id: str) -> dict[str, Any]:
    _require_kb(kb_id)
    return {"kb_id": kb_id, "documents": memory_service.list_kb_documents(kb_id)}


@router.get("/knowledge-bases/{kb_id}/documents/{source}/content")
def get_document_content(kb_id: str, source: str) -> dict[str, Any]:
    _require_kb(kb_id)
    content = kb_service.get_document_content(kb_id, source)
    return {"kb_id": kb_id, "source": source, "content": content}


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}")
def delete_kb_document(kb_id: str, doc_id: str) -> dict[str, Any]:
    _require_kb(kb_id)
    memory_service.delete_kb_document(kb_id, doc_id)
    kb_service.delete_document_vectors(kb_id, doc_id)
    return {"kb_id": kb_id, "deleted_doc_id": doc_id}


@router.post("/knowledge-bases/{kb_id}/upload")
async def upload_kb_document(
    kb_id: str,
    file: UploadFile = File(...),
    chunk_size: int = Form(default=500),
    overlap: int = Form(default=80),
) -> dict[str, Any]:
    _require_kb(kb_id)
    if chunk_size < 100 or chunk_size > 8000:
        raise AppError("invalid_chunk_size", status_code=400)
    if overlap < 0 or overlap > 2000:
        raise AppError("invalid_overlap", status_code=400)
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AppError("file_too_large", status_code=400)
    text = raw.decode("utf-8", errors="replace")
    if not text.strip():
        raise AppError("empty_file", status_code=400)
    doc_id = uuid.uuid4().hex
    title = file.filename or "upload.txt"
    n = kb_service.upsert_documents(
        kb_id,
        [{"text": text, "source": title}],
        chunk_size=chunk_size,
        overlap=overlap,
        doc_id=doc_id,
    )
    memory_service.add_kb_document(doc_id, kb_id, title, "file", n)
    return {"kb_id": kb_id, "doc_id": doc_id, "upserted_chunks": n, "title": title}


@router.get("/sessions/{session_id}/history")
def session_history(session_id: str) -> dict[str, Any]:
    return {"session_id": session_id, "messages": memory_service.get_recent_messages(session_id, limit=100)}


@router.get("/traces/{session_id}")
def session_traces(session_id: str, limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    return {
        "session_id": session_id,
        "traces": memory_service.get_recent_traces(session_id=session_id, limit=safe_limit),
    }


@router.get("/traces/{session_id}/stats")
def session_trace_stats(session_id: str, limit: int = 100) -> dict[str, Any]:
    safe_limit = max(10, min(limit, 500))
    return {
        "session_id": session_id,
        "stats": memory_service.get_trace_stats(session_id=session_id, limit=safe_limit),
    }
