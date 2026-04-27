from typing import Any

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import json

from app.core.logging import new_trace_id
from app.services.cache_service import CacheService
from app.services.chat_service import ChatService
from app.services.kb_service import KnowledgeBaseService
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService

router = APIRouter()

memory_service = MemoryService()
kb_service = KnowledgeBaseService()
retrieval_service = RetrievalService(kb_service=kb_service)
cache_service = CacheService()
chat_service = ChatService(
    memory_service=memory_service,
    retrieval_service=retrieval_service,
    cache_service=cache_service,
)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    question: str = Field(min_length=1)


class KnowledgeDoc(BaseModel):
    text: str = Field(min_length=1)
    source: str = "manual"


class KnowledgeUpsertRequest(BaseModel):
    docs: list[KnowledgeDoc]


@router.post("/chat")
def chat(payload: ChatRequest, x_trace_id: str | None = Header(default=None)) -> dict[str, Any]:
    trace_id = x_trace_id or new_trace_id()
    result = chat_service.ask(
        session_id=payload.session_id,
        question=payload.question,
        trace_id=trace_id,
    )
    result["trace_id"] = trace_id
    return result


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, x_trace_id: str | None = Header(default=None)):
    trace_id = x_trace_id or new_trace_id()

    async def event_gen():
        async for event in chat_service.stream_ask(
            session_id=payload.session_id,
            question=payload.question,
            trace_id=trace_id,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/knowledge/upsert")
def knowledge_upsert(payload: KnowledgeUpsertRequest) -> dict[str, Any]:
    total = kb_service.upsert_documents([d.model_dump() for d in payload.docs])
    return {"upserted_chunks": total}


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
