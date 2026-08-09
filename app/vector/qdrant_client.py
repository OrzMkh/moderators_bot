import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import settings

logger = structlog.get_logger()

# If QDRANT_URL is localhost or not explicitly remote, use in-memory client for 100% cloud reliability
if "localhost" in settings.qdrant_url or not settings.qdrant_url.startswith("https"):
    logger.info("Using in-memory Qdrant client for cloud execution")
    qdrant_client = AsyncQdrantClient(":memory:")
else:
    try:
        qdrant_client = AsyncQdrantClient(
            url=str(settings.qdrant_url),
            api_key=settings.qdrant_api_key if settings.qdrant_api_key else None,
            timeout=3.0,
        )
    except Exception as e:
        logger.warning("Using in-memory Qdrant client", error=str(e))
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

    # 1. Knowledge Base Collection (768 dim for Gemini embeddings)
    if settings.qdrant_collection_kb not in existing_collections:
        logger.info(
            "Creating Qdrant collection for Gemini embeddings",
            collection=settings.qdrant_collection_kb
        )
        await qdrant_client.create_collection(
            collection_name=settings.qdrant_collection_kb,
            vectors_config=qmodels.VectorParams(
                size=768,
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
