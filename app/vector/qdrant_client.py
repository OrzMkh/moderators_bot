import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import settings

logger = structlog.get_logger()

# Global Async Qdrant Client instance (default: try remote URL, fallback to in-memory)
try:
    qdrant_client = AsyncQdrantClient(
        url=str(settings.qdrant_url),
        api_key=settings.qdrant_api_key if settings.qdrant_api_key else None,
        timeout=3.0,
    )
except Exception as e:
    logger.warning("Could not connect to Qdrant server, using in-memory Qdrant client", error=str(e))
    qdrant_client = AsyncQdrantClient(":memory:")


async def init_qdrant_collections() -> None:
    """Creates Qdrant collections if they do not exist."""
    global qdrant_client
    try:
        existing_collections = [
            col.name for col in (await qdrant_client.get_collections()).collections
        ]
    except Exception:
        logger.warning("Switching Qdrant client to in-memory mode")
        qdrant_client = AsyncQdrantClient(":memory:")
        existing_collections = []

    # 1. Knowledge Base Collection (768 dim for Gemini text-embedding-004)
    if settings.qdrant_collection_kb not in existing_collections:
        logger.info(
            "Creating Qdrant collection for Gemini embeddings",
            collection=settings.qdrant_collection_kb
        )
        await qdrant_client.create_collection(
            collection_name=settings.qdrant_collection_kb,
            vectors_config=qmodels.VectorParams(
                size=768,  # Gemini text-embedding-004 dimension
                distance=qmodels.Distance.COSINE,
            ),
        )

    # 2. Courier Short-term Context Collection
    if settings.qdrant_collection_ctx not in existing_collections:
        logger.info(
            "Creating Qdrant collection",
            collection=settings.qdrant_collection_ctx
        )
        await qdrant_client.create_collection(
            collection_name=settings.qdrant_collection_ctx,
            vectors_config=qmodels.VectorParams(
                size=768,
                distance=qmodels.Distance.COSINE,
            ),
        )
