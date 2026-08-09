"""Скрипт для локального тестирования через Long-Polling (без вебхука)."""
import asyncio
import structlog
from aiogram import Bot, Dispatcher

from app.bot.router import main_router
from app.config import settings
from app.db.engine import engine
from app.db.models import Base
from app.vector.qdrant_client import init_qdrant_collections, qdrant_client

logger = structlog.get_logger()


async def main() -> None:
    logger.info("Starting local polling test...")

    # Initialize DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize Qdrant
    try:
        await init_qdrant_collections()
    except Exception as e:
        logger.warning("Qdrant init warning", error=str(e))

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(main_router)

    # Drop old webhooks before polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot is ready and polling for updates!")

    try:
        await dp.start_polling(bot)
    finally:
        await engine.dispose()
        await qdrant_client.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
