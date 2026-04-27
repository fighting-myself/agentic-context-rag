import os
import re
import uuid
from dataclasses import dataclass

import chromadb
from langchain_community.embeddings import DashScopeEmbeddings

from app.core.config import get_settings


@dataclass
class KBChunk:
    chunk_id: str
    text: str
    metadata: dict


class KnowledgeBaseService:
    def __init__(self) -> None:
        self.settings = get_settings()
        os.makedirs(self.settings.chroma_path, exist_ok=True)
        self.client = chromadb.PersistentClient(path=self.settings.chroma_path)
        self.embedder = DashScopeEmbeddings(
            model=self.settings.qwen_embedding_model,
            dashscope_api_key=self.settings.qwen_api_key,
        )

    @staticmethod
    def collection_name(kb_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", kb_id.strip() or "default")[:80]
        return f"kb_{safe}"

    def get_collection(self, kb_id: str):
        return self.client.get_or_create_collection(self.collection_name(kb_id))

    def ensure_collection(self, kb_id: str) -> None:
        self.get_collection(kb_id)

    def split_text(self, text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + chunk_size)
            chunks.append(text[start:end])
            start = end - overlap
            if start < 0:
                start = 0
            if end >= len(text):
                break
        return [c.strip() for c in chunks if c.strip()]

    def upsert_documents(
        self,
        kb_id: str,
        docs: list[dict],
        chunk_size: int = 500,
        overlap: int = 80,
        doc_id: str | None = None,
    ) -> int:
        collection = self.get_collection(kb_id)
        chunks: list[KBChunk] = []
        for d in docs:
            source = d.get("source", "manual")
            extra = {k: v for k, v in d.items() if k not in ("text", "source")}
            chunk_index = 0
            for text in self.split_text(d["text"], chunk_size=chunk_size, overlap=overlap):
                chunk_id = uuid.uuid4().hex
                meta = {
                    "kb_id": kb_id,
                    "source": str(source),
                    "chunk_index": chunk_index,
                    **{k: str(v) for k, v in extra.items() if v is not None},
                }
                if doc_id:
                    meta["doc_id"] = doc_id
                chunks.append(KBChunk(chunk_id=chunk_id, text=text, metadata=meta))
                chunk_index += 1

        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        vectors = self.embedder.embed_documents(texts)
        collection.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=texts,
            metadatas=[c.metadata for c in chunks],
            embeddings=vectors,
        )
        return len(chunks)

    def delete_knowledge_base_vectors(self, kb_id: str) -> None:
        name = self.collection_name(kb_id)
        try:
            self.client.delete_collection(name)
        except Exception:
            pass

    def delete_document_vectors(self, kb_id: str, doc_id: str) -> None:
        collection = self.get_collection(kb_id)
        collection.delete(where={"doc_id": doc_id})

    def get_document_content(self, kb_id: str, source: str) -> str:
        collection = self.get_collection(kb_id)
        results = collection.get(where={"source": source})
        if not results or not results.get("documents"):
            return ""
        
        documents = results["documents"]
        metadatas = results.get("metadatas", [])
        
        sorted_chunks = []
        for i, doc in enumerate(documents):
            metadata = metadatas[i] if i < len(metadatas) else {}
            sorted_chunks.append({
                "text": doc,
                "metadata": metadata
            })
        
        sorted_chunks.sort(key=lambda x: x["metadata"].get("chunk_index", 0))
        
        return "\n\n".join([chunk["text"] for chunk in sorted_chunks])
