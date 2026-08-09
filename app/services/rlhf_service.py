import asyncio
from datetime import datetime, timezone
import uuid
import structlog
from google import genai
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import settings

logger = structlog.get_logger()


class RLHFService:
    def __init__(
        self,
        gemini_client: genai.Client,
        qdrant_client: AsyncQdrantClient,
    ) -> None:
        self._gemini = gemini_client
        self._qdrant = qdrant_client

    async def add_approved_knowledge(
        self,
        question: str,
        answer: str,
        language: str,
        service_type: str | None = None,
        ticket_id: str | None = None,
    ) -> str:
        """Vectorizes and upserts an approved or edited moderator answer into Qdrant KB using Gemini."""
        try:
            def _call_api():
                return self._gemini.models.embed_content(
                    model=settings.gemini_model_embed,
                    contents=question,
                )

            response = await asyncio.to_thread(_call_api)
            vals = response.embedding.values if hasattr(response, "embedding") and response.embedding else response.embeddings[0].values
            vector = list(vals)
            point_id = str(uuid.uuid4())

            payload = {
                "question_original": question,
                "answer": answer,
                "language": language,
                "service_type": service_type or "general",
                "source": "rlhf",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ticket_id": ticket_id,
            }

            await self._qdrant.upsert(
                collection_name=settings.qdrant_collection_kb,
                points=[
                    qmodels.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload,
                    )
                ],
            )
            logger.info("Successfully added RLHF knowledge entry to Qdrant via Gemini", point_id=point_id, ticket_id=ticket_id)
            return point_id
        except Exception as e:
            logger.error("Failed to add RLHF entry to Qdrant", error=str(e), question=question[:50])
            raise
