import json
import logging
import time
from typing import Any, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from app.core.config import get_settings
from app.services.cache_service import CacheService
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService


class ChatState(TypedDict):
    session_id: str
    kb_id: str
    question: str
    rewritten_question: str
    intent: str
    trace_id: str
    history: list[dict[str, Any]]
    contexts: list[dict[str, Any]]
    answer: str
    cache_key: str
    cache_hit: bool
    confidence: float
    citations: list[dict[str, Any]]


class ChatService:
    def __init__(
        self,
        memory_service: MemoryService,
        retrieval_service: RetrievalService,
        cache_service: CacheService,
    ) -> None:
        self.settings = get_settings()
        self.logger = logging.getLogger("app.chat")
        self.memory_service = memory_service
        self.retrieval_service = retrieval_service
        self.cache_service = cache_service
        self.llm = ChatOpenAI(
            model=self.settings.qwen_model,
            api_key=self.settings.qwen_api_key,
            base_url=self.settings.qwen_base_url,
            temperature=0.2,
        )
        self.graph = self._build_graph()

    def _truncate_text(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]}..."

    def _compress_history(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        selected = history[-self.settings.history_prompt_turns :]
        return [
            {
                "role": str(item.get("role", "user")),
                "content": self._truncate_text(
                    str(item.get("content", "")),
                    self.settings.history_item_max_chars,
                ),
            }
            for item in selected
        ]

    def _compress_contexts(self, contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sliced = contexts[: self.settings.context_max_items]
        compressed: list[dict[str, Any]] = []
        for item in sliced:
            compressed.append(
                {
                    **item,
                    "text": self._truncate_text(
                        str(item.get("text", "")),
                        self.settings.context_item_max_chars,
                    ),
                }
            )
        return compressed

    def _classify_intent(self, question: str) -> str:
        q = question.lower()
        if any(k in q for k in ["区别", "对比", "比较", "差异"]):
            return "comparison"
        if any(k in q for k in ["步骤", "怎么做", "如何", "流程"]):
            return "how_to"
        if any(k in q for k in ["为什么", "原因"]):
            return "why"
        return "fact"

    def _rewrite_question(self, question: str, history: list[dict[str, Any]]) -> str:
        q = question.strip().replace("？", "?").replace("，", ",")
        if not history:
            return q
        # 简单追问改写：当问题过短且包含指代词时，拼接最近用户问题提高召回。
        follow_up_tokens = ["它", "这个", "那个", "上面", "刚才", "前面", "该方案"]
        if len(q) <= 18 and any(t in q for t in follow_up_tokens):
            recent_user = ""
            for item in reversed(history):
                if item.get("role") == "user":
                    recent_user = str(item.get("content", "")).strip()
                    break
            if recent_user:
                return f"{recent_user}；补充问题：{q}"
        return q

    def _build_citations(self, contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for item in contexts[:3]:
            citations.append(
                {
                    "source": item.get("metadata", {}).get("source", "unknown"),
                    "snippet": self._truncate_text(str(item.get("text", "")), 120),
                    "score": round(float(item.get("score", 0.0)), 4),
                }
            )
        return citations

    def _estimate_confidence(self, contexts: list[dict[str, Any]], cache_hit: bool) -> float:
        if cache_hit:
            return 0.95
        if not contexts:
            return 0.2
        top_scores = [float(c.get("score", 0.0)) for c in contexts[:3]]
        avg = sum(top_scores) / max(len(top_scores), 1)
        return round(max(0.1, min(0.99, avg)), 4)

    def _build_graph(self):
        graph = StateGraph(ChatState)
        graph.add_node("prepare", self._prepare)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("cache", self._cache_lookup)
        graph.add_node("generate", self._generate)
        graph.add_node("persist", self._persist)
        graph.set_entry_point("prepare")
        graph.add_edge("prepare", "retrieve")
        graph.add_edge("retrieve", "cache")
        graph.add_conditional_edges(
            "cache",
            lambda state: "persist" if state["cache_hit"] else "generate",
            {"persist": "persist", "generate": "generate"},
        )
        graph.add_edge("generate", "persist")
        graph.add_edge("persist", END)
        return graph.compile()

    def _prepare(self, state: ChatState) -> ChatState:
        history = self.memory_service.get_recent_messages(state["session_id"])
        rewritten = self._rewrite_question(state["question"], history)
        intent = self._classify_intent(rewritten)
        cache_key = self.cache_service.build_key(
            state["session_id"], rewritten, history, state.get("kb_id", "default")
        )
        state["history"] = history
        state["rewritten_question"] = rewritten
        state["intent"] = intent
        state["cache_key"] = cache_key
        state["cache_hit"] = False
        return state

    def _retrieve(self, state: ChatState) -> ChatState:
        state["contexts"] = self.retrieval_service.retrieve(
            state["rewritten_question"], state.get("kb_id", "default")
        )
        return state

    def _cache_lookup(self, state: ChatState) -> ChatState:
        cached = self.cache_service.get(state["cache_key"])
        if cached:
            payload = json.loads(cached)
            state["answer"] = payload["answer"]
            state["cache_hit"] = True
            state["citations"] = payload.get("citations", self._build_citations(state["contexts"]))
            state["confidence"] = float(payload.get("confidence", self._estimate_confidence(state["contexts"], True)))
        return state

    def _generate(self, state: ChatState) -> ChatState:
        prompt_contexts = self._compress_contexts(state["contexts"])
        prompt_history = self._compress_history(state["history"])
        context_text = "\n\n".join([f"- {c['text']}" for c in prompt_contexts])
        history_text = "\n".join([f"{h['role']}: {h['content']}" for h in prompt_history])
        prompt = (
            "你是一个企业知识助手。请基于给定知识上下文回答问题，回答要准确简洁。\n"
            f"问题意图: {state['intent']}\n"
            f"历史对话:\n{history_text}\n\n"
            f"知识上下文:\n{context_text}\n\n"
            f"用户问题:\n{state['rewritten_question']}"
        )
        answer = self.llm.invoke(prompt).content
        state["answer"] = answer
        state["citations"] = self._build_citations(state["contexts"])
        state["confidence"] = self._estimate_confidence(state["contexts"], False)
        self.cache_service.set(
            state["cache_key"],
            json.dumps(
                {
                    "answer": answer,
                    "citations": state["citations"],
                    "confidence": state["confidence"],
                },
                ensure_ascii=False,
            ),
            ttl_seconds=300,
        )
        return state

    def _persist(self, state: ChatState) -> ChatState:
        self.memory_service.add_message(state["session_id"], "user", state["question"])
        self.memory_service.add_message(state["session_id"], "assistant", state["answer"])
        self.logger.info(
            "chat_complete",
            extra={
                "trace_id": state["trace_id"],
                "session_id": state["session_id"],
                "cache_hit": state["cache_hit"],
            },
        )
        return state

    def ask(self, session_id: str, question: str, trace_id: str, kb_id: str = "default") -> dict[str, Any]:
        total_start = time.perf_counter()
        state: ChatState = {
            "session_id": session_id,
            "kb_id": kb_id or "default",
            "question": question,
            "rewritten_question": question,
            "intent": "fact",
            "trace_id": trace_id,
            "history": [],
            "contexts": [],
            "answer": "",
            "cache_key": "",
            "cache_hit": False,
            "confidence": 0.0,
            "citations": [],
        }
        retrieve_start = time.perf_counter()
        out = self.graph.invoke(state)
        total_ms = (time.perf_counter() - total_start) * 1000
        retrieve_ms = (time.perf_counter() - retrieve_start) * 1000 if not out["cache_hit"] else 0.0
        llm_ms = total_ms if not out["cache_hit"] else 0.0
        ttft_ms = 5.0 if out["cache_hit"] else llm_ms
        self.memory_service.add_trace(
            trace_id=trace_id,
            session_id=session_id,
            cache_hit=out["cache_hit"],
            retrieve_ms=retrieve_ms,
            llm_ms=llm_ms,
            total_ms=total_ms,
            ttft_ms=ttft_ms,
        )
        return {
            "answer": out["answer"],
            "contexts": out["contexts"],
            "cache_hit": out["cache_hit"],
            "intent": out["intent"],
            "rewritten_question": out["rewritten_question"],
            "confidence": out.get("confidence", 0.0),
            "citations": out.get("citations", []),
            "metrics": {
                "retrieve_ms": round(retrieve_ms, 2),
                "llm_ms": round(llm_ms, 2),
                "total_ms": round(total_ms, 2),
                "ttft_ms": round(ttft_ms, 2),
            },
        }

    async def stream_ask(self, session_id: str, question: str, trace_id: str, kb_id: str = "default"):
        total_start = time.perf_counter()
        kb = kb_id or "default"
        history = self.memory_service.get_recent_messages(session_id)
        rewritten_question = self._rewrite_question(question, history)
        intent = self._classify_intent(rewritten_question)
        cache_key = self.cache_service.build_key(session_id, rewritten_question, history, kb)
        contexts = self.retrieval_service.retrieve(rewritten_question, kb)
        retrieve_ms = (time.perf_counter() - total_start) * 1000

        cached = self.cache_service.get(cache_key)
        if cached:
            payload = json.loads(cached)
            answer = payload["answer"]
            citations = payload.get("citations", self._build_citations(contexts))
            confidence = float(payload.get("confidence", self._estimate_confidence(contexts, True)))
            self.memory_service.add_message(session_id, "user", question)
            self.memory_service.add_message(session_id, "assistant", answer)
            total_ms = (time.perf_counter() - total_start) * 1000
            ttft_ms = 5.0
            self.memory_service.add_trace(
                trace_id=trace_id,
                session_id=session_id,
                cache_hit=True,
                retrieve_ms=0.0,
                llm_ms=0.0,
                total_ms=total_ms,
                ttft_ms=ttft_ms,
            )
            self.logger.info(
                "chat_stream_complete",
                extra={
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "cache_hit": True,
                    "total_ms": total_ms,
                },
            )
            yield {
                "type": "meta",
                "trace_id": trace_id,
                "cache_hit": True,
                "contexts": contexts,
                "intent": intent,
                "rewritten_question": rewritten_question,
                "citations": citations,
                "confidence": confidence,
            }
            yield {"type": "token", "delta": answer}
            yield {
                "type": "done",
                "metrics": {
                    "retrieve_ms": 0.0,
                    "llm_ms": 0.0,
                    "total_ms": round(total_ms, 2),
                    "ttft_ms": ttft_ms,
                },
            }
            return

        prompt_contexts = self._compress_contexts(contexts)
        prompt_history = self._compress_history(history)
        context_text = "\n\n".join([f"- {c['text']}" for c in prompt_contexts])
        history_text = "\n".join([f"{h['role']}: {h['content']}" for h in prompt_history])
        prompt = (
            "你是一个企业知识助手。请基于给定知识上下文回答问题，回答要准确简洁。\n"
            f"问题意图: {intent}\n"
            f"历史对话:\n{history_text}\n\n"
            f"知识上下文:\n{context_text}\n\n"
            f"用户问题:\n{rewritten_question}"
        )

        citations = self._build_citations(contexts)
        confidence = self._estimate_confidence(contexts, False)
        yield {
            "type": "meta",
            "trace_id": trace_id,
            "cache_hit": False,
            "contexts": contexts,
            "intent": intent,
            "rewritten_question": rewritten_question,
            "citations": citations,
            "confidence": confidence,
        }

        answer_parts: list[str] = []
        llm_start = time.perf_counter()
        ttft_ms = 0.0
        first_token = True
        async for chunk in self.llm.astream(prompt):
            delta = chunk.content or ""
            if not delta:
                continue
            if first_token:
                ttft_ms = (time.perf_counter() - total_start) * 1000
                first_token = False
            answer_parts.append(delta)
            yield {"type": "token", "delta": delta}

        answer = "".join(answer_parts)
        llm_ms = (time.perf_counter() - llm_start) * 1000
        total_ms = (time.perf_counter() - total_start) * 1000
        self.cache_service.set(
            cache_key,
            json.dumps(
                {
                    "answer": answer,
                    "citations": citations,
                    "confidence": confidence,
                },
                ensure_ascii=False,
            ),
            ttl_seconds=300,
        )
        self.memory_service.add_message(session_id, "user", question)
        self.memory_service.add_message(session_id, "assistant", answer)
        self.memory_service.add_trace(
            trace_id=trace_id,
            session_id=session_id,
            cache_hit=False,
            retrieve_ms=retrieve_ms,
            llm_ms=llm_ms,
            total_ms=total_ms,
            ttft_ms=ttft_ms,
        )
        self.logger.info(
            "chat_stream_complete",
            extra={
                "trace_id": trace_id,
                "session_id": session_id,
                "cache_hit": False,
                "retrieve_ms": round(retrieve_ms, 2),
                "llm_ms": round(llm_ms, 2),
                "total_ms": round(total_ms, 2),
                "ttft_ms": round(ttft_ms, 2),
            },
        )
        yield {
            "type": "done",
            "metrics": {
                "retrieve_ms": round(retrieve_ms, 2),
                "llm_ms": round(llm_ms, 2),
                "total_ms": round(total_ms, 2),
                "ttft_ms": round(ttft_ms, 2),
            },
        }
