import os
import uuid
from dataclasses import dataclass

import chromadb
from langchain_openai import OpenAIEmbeddings

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
        self.collection = self.client.get_or_create_collection("knowledge_base")
        self.embedder = OpenAIEmbeddings(
            model=self.settings.qwen_embedding_model,
            api_key=self.settings.qwen_api_key,
            base_url=self.settings.qwen_base_url,
        )

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

    def upsert_documents(self, docs: list[dict]) -> int:
        chunks: list[KBChunk] = []
        for d in docs:
            source = d.get("source", "manual")
            for text in self.split_text(d["text"]):
                chunk_id = uuid.uuid4().hex
                chunks.append(
                    KBChunk(
                        chunk_id=chunk_id,
                        text=text,
                        metadata={"source": source},
                    )
                )

        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        vectors = self.embedder.embed_documents(texts)
        self.collection.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=texts,
            metadatas=[c.metadata for c in chunks],
            embeddings=vectors,
        )
        return len(chunks)
