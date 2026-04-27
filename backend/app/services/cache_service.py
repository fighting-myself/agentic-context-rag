import hashlib
import json
import re
from typing import Any

import redis
from redis.exceptions import RedisError

from app.core.config import get_settings


class CacheService:
    def __init__(self) -> None:
        settings = get_settings()
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self._local_cache: dict[str, str] = {}
        self._redis_ok = True
        try:
            self.client.ping()
        except RedisError:
            self._redis_ok = False

    @staticmethod
    def _normalize_text(text: str) -> str:
        lowered = text.lower().strip()
        collapsed = re.sub(r"\s+", " ", lowered)
        return re.sub(r"[^\w\s\u4e00-\u9fff]", "", collapsed)

    @classmethod
    def _normalize_history(cls, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in history[-6:]:
            normalized.append(
                {
                    "role": str(item.get("role", "")).strip().lower(),
                    "content": cls._normalize_text(str(item.get("content", ""))),
                }
            )
        return normalized

    @classmethod
    def build_key(session_id: str, question: str, history: list[dict[str, Any]]) -> str:
        raw = json.dumps(
            {
                "session_id": session_id,
                "question": CacheService._normalize_text(question),
                "history": CacheService._normalize_history(history),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return f"chat_cache:{digest}"

    def get(self, key: str) -> str | None:
        if self._redis_ok:
            return self.client.get(key)
        return self._local_cache.get(key)

    def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        if self._redis_ok:
            self.client.setex(key, ttl_seconds, value)
        else:
            self._local_cache[key] = value
