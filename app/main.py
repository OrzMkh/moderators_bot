from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request, Response, status

from app.bot.router import main_router
from app.config import settings
from app.db.engine import engine
from app.db.models import Base
from app.vector.qdrant_client import init_qdrant_collections, qdrant_client

logger = structlog.get_logger()

# Initialize Bot & Dispatcher
bot = Bot(token=settings.bot_token)
dp = Dispatcher()
dp.include_router(main_router)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Управление ресурсами на старте и завершении приложения."""
    logger.info("Starting Courier Support Bot Service...", port=settings.port)

    # 1. Инициализация таблиц PostgreSQL
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("PostgreSQL tables initialized")

    # 2. Инициализация коллекций Qdrant
    try:
        await init_qdrant_collections()
        logger.info("Qdrant collections initialized successfully")
    except Exception as e:
        logger.warning("Could not initialize Qdrant collections on startup", error=str(e))

    # 3. Установка Webhook (если задан RENDER_EXTERNAL_URL)
    if settings.render_external_url:
        webhook_url = f"{str(settings.render_external_url).rstrip('/')}/webhook"
        await bot.set_webhook(
            url=webhook_url,
            secret_token=settings.webhook_secret,
        )
        logger.info("Telegram Webhook set", url=webhook_url)

    yield

    # Shutdown
    logger.info("Shutting down Courier Support Bot Service...")
    await engine.dispose()
    await qdrant_client.close()
    await bot.session.close()


app = FastAPI(
    title="Courier Support Bot API",
    version="0.1.0",
    lifespan=lifespan
)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, str]:
    """Эндпоинт для проверки здоровья сервера и пинга от Cron."""
    return {"status": "ok", "service": "courier-bot"}


@app.post("/webhook")
async def telegram_webhook(request: Request) -> Response:
    """Точка входа для всех входящих обновлений от Telegram."""
    # Verify secret header
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_header != settings.webhook_secret:
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return Response(status_code=status.HTTP_200_OK)
