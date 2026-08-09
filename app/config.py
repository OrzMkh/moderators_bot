from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram
    bot_token: str
    webhook_secret: str = "courier_webhook_secret_key"
    supergroup_id: int
    moderator_chat_id: int

    # Gemini API
    gemini_api_key: str
    gemini_model_chat: str = "gemini-2.0-flash"
    gemini_model_intent: str = "gemini-2.0-flash"
    gemini_model_embed: str = "gemini-embedding-001"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/courier_db"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection_kb: str = "knowledge_base"
    qdrant_collection_ctx: str = "courier_context"

    # RAG
    rag_confidence_threshold: float = 0.85
    rag_search_limit: int = 5

    # Server
    render_external_url: str | None = None
    port: int = 8000

    @field_validator("render_external_url", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: str | None) -> str | None:
        if not v:
            return None
        return v


settings = Settings()
