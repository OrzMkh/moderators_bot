import structlog
from aiogram import F, Router, Bot
from aiogram.types import Message
from google import genai
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.repositories.courier_repo import CourierRepository
from app.db.repositories.message_log_repo import MessageLogRepository
from app.db.repositories.ticket_repo import TicketRepository
from app.bot.keyboards.moderator_kb import get_moderator_ticket_keyboard
from app.services.intent_classifier import IntentClassifierService
from app.services.llm_service import LLMAnswerService
from app.services.rag_service import RAGService
from app.vector.qdrant_client import qdrant_client

logger = structlog.get_logger()

group_router = Router()
# Filter: allow private, group, and supergroup EXCEPT the moderator chat itself
group_router.message.filter(
    F.chat.type.in_({"private", "group", "supergroup"}),
    F.chat.id != settings.moderator_chat_id,
)

# Initialize native Google GenAI SDK Client
genai_sdk_client = genai.Client(api_key=settings.gemini_api_key)

intent_service = IntentClassifierService(genai_sdk_client)
rag_service = RAGService(genai_sdk_client, qdrant_client)
llm_service = LLMAnswerService(genai_sdk_client)


@group_router.message(F.text & ~F.text.startswith("/"))
async def handle_supergroup_message(message: Message, session: AsyncSession, bot: Bot) -> None:
    """Main handler for courier messages in the supergroup or private chat."""
    if not message.from_user:
        return

    user = message.from_user
    courier_repo = CourierRepository(session)
    msg_repo = MessageLogRepository(session)
    ticket_repo = TicketRepository(session)

    # 1. Get or create courier record
    courier = await courier_repo.get_or_create(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name,
    )

    text = message.text or ""
    logger.info("Received courier message", user_id=user.id, text=text, chat_type=message.chat.type)

    # 2. Intent Classification
    intent_result = await intent_service.classify(text)
    logger.info(
        "Intent classified via Gemini",
        user_id=user.id,
        intent=intent_result.intent,
        confidence=intent_result.confidence,
    )

    # 3. Log initial message
    log_entry = await msg_repo.log_message(
        courier_id=courier.id,
        telegram_msg_id=message.message_id,
        chat_id=message.chat.id,
        raw_text=text,
        detected_language=courier.language,
        intent_label=intent_result.intent,
        intent_confidence=intent_result.confidence,
    )

    # If flood in group (not private), ignore completely
    bot_info = await bot.me()
    bot_username = bot_info.username or ""
    if message.chat.type != "private" and intent_result.intent == "flood" and f"@{bot_username}" not in text:
        logger.info("Ignoring flood message", courier_id=str(courier.id))
        return

    # 4. RAG Search in Knowledge Base
    rag_matches = await rag_service.search(text, limit=3)
    best_match = rag_matches[0] if rag_matches else None
    rag_score = best_match.score if best_match else 0.0

    log_entry.rag_score = rag_score

    # 5. Route: High Confidence RAG -> Auto Reply
    if best_match and rag_score >= settings.rag_confidence_threshold:
        logger.info("High RAG confidence match, auto-replying", score=rag_score)
        await message.reply(best_match.answer)
        log_entry.was_auto_replied = True
        return

    # 6. Route: Low Confidence -> Generate Draft & Route to Moderator Chat
    context_str = f"Похожий вопрос из базы: {best_match.question_original}\nОтвет: {best_match.answer}" if best_match else None
    draft_answer = await llm_service.generate_draft_answer(
        question=text,
        language=courier.language,
        rag_context=context_str,
    )

    ticket = await ticket_repo.create_ticket(
        message_log_id=log_entry.id,
        courier_id=courier.id,
        draft_answer=draft_answer,
    )

    # Send ticket card to Moderator Chat
    ticket_card_text = (
        f"🚨 <b>НОВЫЙ ВОПРОС КУРЬЕРА</b>\n\n"
        f"<b>Курьер:</b> {user.full_name} (@{user.username or 'без юзернейма'})\n"
        f"<b>Язык:</b> {courier.language}\n"
        f"<b>Вопрос:</b> {text}\n\n"
        f"🔍 <b>RAG Score:</b> {rag_score:.2f}\n"
        f"💡 <b>Черновик AI (Gemini):</b> {draft_answer}"
    )

    mod_msg = await bot.send_message(
        chat_id=settings.moderator_chat_id,
        text=ticket_card_text,
        reply_markup=get_moderator_ticket_keyboard(str(ticket.id)),
        parse_mode="HTML",
    )

    ticket.moderator_chat_msg_id = mod_msg.message_id
    logger.info("Created ticket for moderator approval", ticket_id=str(ticket.id))
