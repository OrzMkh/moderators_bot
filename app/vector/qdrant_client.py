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


async def ensure_collection(collection_name: str, dim: int = 3072) -> None:
    """Ensures collection exists and has matching vector dimension."""
    global qdrant_client
    try:
        collections = (await qdrant_client.get_collections()).collections
        existing = [c.name for c in collections]
        if collection_name in existing:
            try:
                info = await qdrant_client.get_collection(collection_name)
                vec_params = info.config.params.vectors
                current_dim = getattr(vec_params, "size", None)
                if current_dim and current_dim != dim:
                    logger.info("Recreating Qdrant collection with matching dim", collection=collection_name, old_dim=current_dim, new_dim=dim)
                    await qdrant_client.delete_collection(collection_name)
                    existing.remove(collection_name)
            except Exception:
                pass

        if collection_name not in existing:
            await qdrant_client.create_collection(
                collection_name=collection_name,
                vectors_config=qmodels.VectorParams(
                    size=dim,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection", collection=collection_name, dim=dim)
    except Exception as e:
        logger.warning("Error ensuring Qdrant collection", error=str(e))


async def init_qdrant_collections() -> None:
    """Creates Qdrant collections if they do not exist."""
    await ensure_collection(settings.qdrant_collection_kb, 3072)
    await ensure_collection(settings.qdrant_collection_ctx, 3072)
