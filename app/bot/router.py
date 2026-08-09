from aiogram import Router

from app.bot.handlers.group_messages import group_router
from app.bot.handlers.moderator import moderator_router
from app.bot.middlewares.db_session import DbSessionMiddleware

main_router = Router()

# Register middlewares
main_router.message.middleware(DbSessionMiddleware())
main_router.callback_query.middleware(DbSessionMiddleware())

# Include moderator router FIRST so FSM states and moderator chat messages are caught before group router
main_router.include_router(moderator_router)
main_router.include_router(group_router)
