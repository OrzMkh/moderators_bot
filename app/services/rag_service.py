from dataclasses import dataclass
import structlog
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient

from app.config import settings
from app.vector.qdrant_client import ensure_collection

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
        gemini_client: any,
        qdrant_client: AsyncQdrantClient,
    ) -> None:
        self._openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self._qdrant = qdrant_client

    async def get_embedding(self, text: str) -> list[float]:
        """Generates embedding vector using OpenAI compatible Gemini endpoint."""
        response = await self._openai_client.embeddings.create(
            model=settings.gemini_model_embed,
            input=text,
        )
        return response.data[0].embedding

    async def search(self, query: str, limit: int = 5) -> list[RAGMatch]:
        """Searches vector DB for matching knowledge base entries."""
        try:
            vector = await self.get_embedding(query)
            await ensure_collection(settings.qdrant_collection_kb, len(vector))

            # Compatible search call for all qdrant-client versions
            if hasattr(self._qdrant, "query_points"):
                res = await self._qdrant.query_points(
                    collection_name=settings.qdrant_collection_kb,
                    query=vector,
                    limit=limit,
                )
                search_result = getattr(res, "points", [])
            elif hasattr(self._qdrant, "search"):
                search_result = await self._qdrant.search(
                    collection_name=settings.qdrant_collection_kb,
                    query_vector=vector,
                    limit=limit,
                )
            else:
                search_result = []

            matches: list[RAGMatch] = []
            for hit in search_result:
                payload = getattr(hit, "payload", {}) or {}
                score = getattr(hit, "score", 0.0)
                matches.append(
                    RAGMatch(
                        question_original=payload.get("question_original", ""),
                        answer=payload.get("answer", ""),
                        score=score,
                        language=payload.get("language", "ru"),
                        source=payload.get("source", "unknown"),
                    )
                )
            return matches
        except Exception as e:
            logger.error("RAG search failed", error=str(e), query=query[:50])
            return []
