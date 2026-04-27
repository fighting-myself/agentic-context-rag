from collections import defaultdict
from typing import Any

from rank_bm25 import BM25Okapi

from app.core.config import get_settings
from app.services.kb_service import KnowledgeBaseService


class RetrievalService:
    def __init__(self, kb_service: KnowledgeBaseService) -> None:
        self.settings = get_settings()
        self.kb_service = kb_service

    def _tokenize(self, text: str) -> list[str]:
        return [t for t in text.lower().replace("\n", " ").split(" ") if t]

    def _jaccard(self, a: str, b: str) -> float:
        sa = set(self._tokenize(a))
        sb = set(self._tokenize(b))
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def retrieve(self, question: str, kb_id: str = "default") -> list[dict[str, Any]]:
        collection = self.kb_service.get_collection(kb_id)
        embedding = self.kb_service.embedder.embed_query(question)
        vector_res = collection.query(
            query_embeddings=[embedding],
            n_results=max(self.settings.retrieve_k_vector, self.settings.retrieve_k_final * 3),
            include=["documents", "metadatas", "distances"],
        )

        merged = defaultdict(lambda: {"text": "", "metadata": {}, "vector": 0.0, "bm25": 0.0})
        v_docs = vector_res.get("documents", [[]])[0]
        v_metas = vector_res.get("metadatas", [[]])[0]
        v_dists = vector_res.get("distances", [[]])[0]

        for text, meta, dist in zip(v_docs, v_metas, v_dists):
            merged[text]["text"] = text
            merged[text]["metadata"] = meta or {}
            merged[text]["vector"] = 1.0 / (1.0 + float(dist))

        # Phase-2 rerank: only run BM25 on vector candidates to reduce latency.
        candidate_docs = list(merged.keys())
        if candidate_docs:
            corpus = [self._tokenize(t) for t in candidate_docs]
            bm25 = BM25Okapi(corpus)
            scores = bm25.get_scores(self._tokenize(question))
            for idx, score in enumerate(scores):
                merged[candidate_docs[idx]]["bm25"] = float(score)

        ranked = []
        for item in merged.values():
            final_score = 0.6 * item["vector"] + 0.4 * item["bm25"]
            ranked.append(
                {
                    "text": item["text"],
                    "metadata": item["metadata"],
                    "score": final_score,
                }
            )
        ranked.sort(key=lambda x: x["score"], reverse=True)

        diverse: list[dict[str, Any]] = []
        source_count: dict[str, int] = defaultdict(int)
        for candidate in ranked:
            source = str(candidate.get("metadata", {}).get("source", "unknown"))
            if source_count[source] >= self.settings.retrieve_source_max_per_source:
                continue
            too_similar = False
            for chosen in diverse:
                if self._jaccard(candidate["text"], chosen["text"]) >= self.settings.retrieve_dedup_jaccard_threshold:
                    too_similar = True
                    break
            if too_similar:
                continue
            diverse.append(candidate)
            source_count[source] += 1
            if len(diverse) >= self.settings.retrieve_k_final:
                break
        return diverse
