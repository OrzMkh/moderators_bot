import uuid
import structlog
from aiogram import F, Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.repositories.ticket_repo import TicketRepository
from app.bot.keyboards.moderator_kb import ModeratorAction
from app.services.rlhf_service import RLHFService
from app.vector.qdrant_client import qdrant_client

logger = structlog.get_logger()

moderator_router = Router()

rlhf_service = RLHFService(None, qdrant_client)


class ModeratorStates(StatesGroup):
    waiting_for_edit_text = State()


@moderator_router.callback_query(ModeratorAction.filter(F.action == "approve"))
async def handle_approve_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Moderator approves draft answer as-is."""
    if not query.from_user or not query.message:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_by_id(ticket_id)

    if not ticket or ticket.status != "pending":
        await query.answer("Тикет уже обработан или не найден.", show_alert=True)
        return

    final_answer = ticket.draft_answer

    # 1. Update ticket in DB
    await ticket_repo.update_status(
        ticket_id=ticket_id,
        status="approved",
        moderator_tg_id=query.from_user.id,
        final_answer=final_answer,
        was_edited=False,
    )

    # 2. Reply to Courier in Supergroup / PM
    if ticket.message_log:
        try:
            await bot.send_message(
                chat_id=ticket.message_log.chat_id,
                text=final_answer,
                reply_to_message_id=ticket.message_log.telegram_msg_id,
            )
            logger.info("Sent approved answer to courier", chat_id=ticket.message_log.chat_id)
        except Exception as e:
            logger.error("Failed to send message to courier", error=str(e))

    # 3. Update Moderator Chat Message Card
    mod_name = query.from_user.full_name
    updated_card_text = (
        query.message.html_text + f"\n\n✅ <b>ОДОБРЕНО МОДЕРАТОРОМ</b> (@{query.from_user.username or mod_name})"
    )
    try:
        await query.message.edit_text(text=updated_card_text, parse_mode="HTML", reply_markup=None)
        await query.answer("Ответ одобрен и отправлен курьеру!")
    except Exception as e:
        logger.error("Failed to update moderator message card", error=str(e))

    # 4. Async Vectorize Q&A into Qdrant KB via Gemini (RLHF Loop)
    try:
        await rlhf_service.add_approved_knowledge(
            question=ticket.message_log.raw_text if ticket.message_log else "",
            answer=final_answer,
            language=ticket.courier.language if ticket.courier else "ru",
            ticket_id=str(ticket.id),
        )
        ticket.rlhf_vectorized = True
    except Exception as e:
        logger.error("RLHF vectorization skipped or failed on approval", error=str(e))


@moderator_router.callback_query(ModeratorAction.filter(F.action == "edit"))
async def handle_start_edit_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Moderator clicks Edit button -> enter FSM state to wait for text input."""
    if not query.message:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_by_id(ticket_id)

    if not ticket or ticket.status != "pending":
        await query.answer("Тикет уже обработан.", show_alert=True)
        return

    await state.set_state(ModeratorStates.waiting_for_edit_text)
    await state.update_data(ticket_id=str(ticket.id), card_msg_id=query.message.message_id)

    await query.message.reply(
        f"✏️ Отправьте новым сообщением ответ курьеру для тикета <code>{ticket.id}</code>:"
    )
    await query.answer()


@moderator_router.message(ModeratorStates.waiting_for_edit_text)
@moderator_router.message(F.chat.id == settings.moderator_chat_id, F.reply_to_message)
async def handle_receive_edited_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Moderator sends the edited answer text."""
    if not message.text or not message.from_user or message.text.startswith("/"):
        return

    data = await state.get_data()
    ticket_id_raw = data.get("ticket_id")
    card_msg_id = data.get("card_msg_id")

    # Fallback: Extract ticket_id from reply message if state was reset
    if not ticket_id_raw and message.reply_to_message and message.reply_to_message.text:
        reply_text = message.reply_to_message.text
        if "тикета" in reply_text:
            parts = reply_text.split("тикета")
            if len(parts) > 1:
                candidate = parts[1].strip().strip(":").strip()
                try:
                    ticket_id_raw = str(uuid.UUID(candidate))
                except ValueError:
                    pass

    if not ticket_id_raw:
        # Ignore normal chat chatter in moderator group
        return

    ticket_id = uuid.UUID(ticket_id_raw)
    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_by_id(ticket_id)

    if not ticket or ticket.status != "pending":
        await message.reply("⚠️ Ошибка: Тикет уже был обработан ранее.")
        await state.clear()
        return

    edited_answer = message.text

    # 1. Update ticket in DB
    await ticket_repo.update_status(
        ticket_id=ticket_id,
        status="edited",
        moderator_tg_id=message.from_user.id,
        final_answer=edited_answer,
        was_edited=True,
    )

    # 2. Reply to Courier in Supergroup / PM
    if ticket.message_log:
        try:
            await bot.send_message(
                chat_id=ticket.message_log.chat_id,
                text=edited_answer,
                reply_to_message_id=ticket.message_log.telegram_msg_id,
            )
            logger.info("Sent edited answer to courier", chat_id=ticket.message_log.chat_id)
        except Exception as e:
            logger.error("Failed to send edited message to courier", error=str(e))

    # 3. Notify moderator chat
    if card_msg_id:
        try:
            await bot.send_message(
                chat_id=message.chat.id,
                text=f"✏️ <b>ОТВЕТ ОТРЕДАКТИРОВАН И ОТПРАВЛЕН КУРЬЕРУ</b>\n\n<b>Итоговый текст:</b>\n{edited_answer}",
                reply_to_message_id=card_msg_id,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Failed to notify moderator chat", error=str(e))

    await state.clear()
    await message.reply("✅ Исправленный ответ успешно сохранен и отправлен курьеру!")

    # 4. RLHF Vectorization in Qdrant KB via Gemini
    try:
        await rlhf_service.add_approved_knowledge(
            question=ticket.message_log.raw_text if ticket.message_log else "",
            answer=edited_answer,
            language=ticket.courier.language if ticket.courier else "ru",
            ticket_id=str(ticket.id),
        )
        ticket.rlhf_vectorized = True
    except Exception as e:
        logger.error("RLHF vectorization skipped or failed on edit", error=str(e))
