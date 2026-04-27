from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "agentic-context-rag"
    api_prefix: str = "/api/v1"
    qwen_api_key: str = ""
    qwen_model: str = "qwen3-vl-plus"
    qwen_embedding_model: str = "text-embedding-v3"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    redis_url: str = "redis://redis:6379/0"
    sqlite_path: str = "backend/data/app.db"
    chroma_path: str = "backend/data/chroma"

    log_path: str = "backend/logs/app.log"
    log_level: str = "INFO"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5

    history_limit: int = 100
    history_prompt_turns: int = 5
    history_item_max_chars: int = 180
    history_summary_turns: int = 5
    history_summary_max_chars: int = 200
    context_item_max_chars: int = 500
    context_max_items: int = 4
    retrieve_k_vector: int = 8
    retrieve_k_bm25: int = 8
    retrieve_k_final: int = 5
    retrieve_source_max_per_source: int = 2
    retrieve_dedup_jaccard_threshold: float = 0.82
    state_management_max_chars: int = 500

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
