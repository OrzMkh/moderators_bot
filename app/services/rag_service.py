import asyncio
from dataclasses import dataclass
import structlog
from google import genai
from qdrant_client import AsyncQdrantClient

from app.config import settings

logger = structlog.get_logger()


@dataclass
class RAGMatch:
    question_original: str
    answer: str
    score: float
    language: str
    source: str


class RAGService:
    def __init__(
        self,
        gemini_client: genai.Client,
        qdrant_client: AsyncQdrantClient,
    ) -> None:
        self._gemini = gemini_client
        self._qdrant = qdrant_client

    async def get_embedding(self, text: str) -> list[float]:
        """Generates embedding vector using Gemini gemini-embedding-001 (non-blocking thread)."""
        def _call_api():
            return self._gemini.models.embed_content(
                model=settings.gemini_model_embed,
                contents=text,
            )

        response = await asyncio.to_thread(_call_api)
        vals = response.embedding.values if hasattr(response, "embedding") and response.embedding else response.embeddings[0].values
        return list(vals)

    async def search(self, query: str, limit: int = 5) -> list[RAGMatch]:
        """Searches vector DB for matching knowledge base entries."""
        try:
            vector = await self.get_embedding(query)
            search_result = await self._qdrant.search(
                collection_name=settings.qdrant_collection_kb,
                query_vector=vector,
                limit=limit,
            )

            matches: list[RAGMatch] = []
            for hit in search_result:
                payload = hit.payload or {}
                matches.append(
                    RAGMatch(
                        question_original=payload.get("question_original", ""),
                        answer=payload.get("answer", ""),
                        score=hit.score,
                        language=payload.get("language", "ru"),
                        source=payload.get("source", "unknown"),
                    )
                )
            return matches
        except Exception as e:
            logger.error("RAG search failed", error=str(e), query=query[:50])
            return []
