from datetime import datetime, timezone
import uuid
import structlog
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import settings
from app.vector.qdrant_client import ensure_collection

logger = structlog.get_logger()


class RLHFService:
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

    async def add_approved_knowledge(
        self,
        question: str,
        answer: str,
        language: str,
        service_type: str | None = None,
        ticket_id: str | None = None,
    ) -> str:
        """Vectorizes and upserts an approved or edited moderator answer into Qdrant KB using Gemini embeddings."""
        try:
            response = await self._openai_client.embeddings.create(
                model=settings.gemini_model_embed,
                input=question,
            )
            vector = response.data[0].embedding
            await ensure_collection(settings.qdrant_collection_kb, len(vector))
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
