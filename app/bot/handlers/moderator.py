import uuid
import structlog
from aiogram import F, Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.repositories.ticket_repo import TicketRepository
from app.bot.keyboards.moderator_kb import (
    ModeratorAction,
    get_confirm_send_keyboard,
    get_moderator_ticket_keyboard,
)
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

    if not ticket or ticket.status not in ("pending", "waiting_edit", "waiting_confirm"):
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
    """Moderator clicks Edit button -> set ticket state in DB & FSM."""
    if not query.message or not query.from_user:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_by_id(ticket_id)

    if not ticket or ticket.status not in ("pending", "waiting_edit", "waiting_confirm"):
        await query.answer("Тикет уже обработан.", show_alert=True)
        return

    # Mark ticket as waiting_edit in Database for persistent stateless webhooks
    await ticket_repo.set_waiting_edit(ticket_id=ticket_id, moderator_tg_id=query.from_user.id)

    await state.set_state(ModeratorStates.waiting_for_edit_text)
    await state.update_data(ticket_id=str(ticket.id), card_msg_id=query.message.message_id)

    # Disable buttons on original card to prevent accidental approval while editing
    try:
        await query.message.edit_text(
            text=query.message.html_text + "\n\n✏️ <i>(Ожидается ввод нового текста ответа...)</i>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass

    await query.message.reply(
        f"✏️ Отправьте новым сообщением исправленный текст ответа курьеру:"
    )
    await query.answer()


@moderator_router.message(F.chat.id == settings.moderator_chat_id)
@moderator_router.message(ModeratorStates.waiting_for_edit_text)
async def handle_receive_edited_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Moderator sends text -> show confirmation card before sending to courier."""
    if not message.text or not message.from_user or message.text.startswith("/"):
        return

    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_waiting_edit_ticket(message.from_user.id)

    if not ticket:
        data = await state.get_data()
        ticket_id_raw = data.get("ticket_id")
        if ticket_id_raw:
            ticket = await ticket_repo.get_by_id(uuid.UUID(ticket_id_raw))

    if not ticket:
        # Ignore regular banter between moderators
        return

    edited_answer = message.text

    # Store candidate final_answer in DB & update status to waiting_confirm
    ticket.final_answer = edited_answer
    ticket.status = "waiting_confirm"
    await session.flush()

    await state.clear()

    confirm_card_text = (
        f"📋 <b>ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР ОТВЕТА КУРЬЕРУ:</b>\n\n"
        f"<i>«{edited_answer}»</i>\n\n"
        f"Отправить этот текст курьеру?"
    )

    await message.reply(
        text=confirm_card_text,
        reply_markup=get_confirm_send_keyboard(str(ticket.id)),
        parse_mode="HTML",
    )


@moderator_router.callback_query(ModeratorAction.filter(F.action == "confirm_send"))
async def handle_confirm_send_edited(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Moderator clicks '🚀 Да, отправить курьеру'."""
    if not query.from_user or not query.message:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_by_id(ticket_id)

    if not ticket or not ticket.final_answer:
        await query.answer("Ошибка: Текст ответа не найден.", show_alert=True)
        return

    final_answer = ticket.final_answer

    # 1. Mark status as edited
    await ticket_repo.update_status(
        ticket_id=ticket_id,
        status="edited",
        moderator_tg_id=query.from_user.id,
        final_answer=final_answer,
        was_edited=True,
    )

    # 2. Reply to Courier in Supergroup / PM
    if ticket.message_log:
        try:
            await bot.send_message(
                chat_id=ticket.message_log.chat_id,
                text=final_answer,
                reply_to_message_id=ticket.message_log.telegram_msg_id,
            )
            logger.info("Sent confirmed edited answer to courier", chat_id=ticket.message_log.chat_id)
        except Exception as e:
            logger.error("Failed to send message to courier", error=str(e))

    # 3. Update Confirmation Card Message in Moderator Chat
    mod_name = query.from_user.full_name
    updated_card_text = (
        f"🚀 <b>ОТВЕТ УСПЕШНО ОТПРАВЛЕН КУРЬЕРУ</b> (@{query.from_user.username or mod_name})\n\n"
        f"<b>Итоговый текст:</b>\n<i>«{final_answer}»</i>"
    )
    try:
        await query.message.edit_text(text=updated_card_text, parse_mode="HTML", reply_markup=None)
        await query.answer("Ответ успешно отправлен курьеру!")
    except Exception as e:
        logger.error("Failed to update confirm message card", error=str(e))

    # 4. RLHF Vectorization
    try:
        await rlhf_service.add_approved_knowledge(
            question=ticket.message_log.raw_text if ticket.message_log else "",
            answer=final_answer,
            language=ticket.courier.language if ticket.courier else "ru",
            ticket_id=str(ticket.id),
        )
        ticket.rlhf_vectorized = True
    except Exception as e:
        logger.error("RLHF vectorization skipped or failed on confirm edit", error=str(e))


@moderator_router.callback_query(ModeratorAction.filter(F.action == "reedit"))
async def handle_reedit_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Moderator clicks '✏️ Изменить еще раз'."""
    if not query.message or not query.from_user:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    await ticket_repo.set_waiting_edit(ticket_id=ticket_id, moderator_tg_id=query.from_user.id)

    await state.set_state(ModeratorStates.waiting_for_edit_text)
    await state.update_data(ticket_id=str(ticket_id), card_msg_id=query.message.message_id)

    await query.message.edit_text(
        text="✏️ Введите новый исправленный текст ответа курьеру:",
        reply_markup=None,
    )
    await query.answer()


@moderator_router.callback_query(ModeratorAction.filter(F.action == "cancel"))
async def handle_cancel_edit_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Moderator clicks '❌ Отменить'."""
    if not query.message:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_by_id(ticket_id)
    if ticket:
        ticket.status = "pending"
        await session.flush()

    await state.clear()
    await query.message.edit_text(
        text="❌ Редактирование отменено. Карточка возвращена в исходное состояние.",
        reply_markup=get_moderator_ticket_keyboard(str(ticket_id)),
    )
    await query.answer("Отменено.")
