import html
import uuid
import structlog
from aiogram import Router, Bot
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

# Global in-memory edit tracking: moderator_tg_id -> ticket_id (UUID string)
_pending_edit: dict[int, str] = {}


@moderator_router.callback_query(ModeratorAction.filter(F.action == "approve"))
async def handle_approve_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if not query.from_user or not query.message:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_by_id(ticket_id)

    if not ticket or ticket.status not in ("pending", "waiting_edit", "waiting_confirm"):
        await query.answer("Тикет уже обработан или не найден.", show_alert=True)
        return

    final_answer = ticket.draft_answer

    await ticket_repo.update_status(
        ticket_id=ticket_id,
        status="approved",
        moderator_tg_id=query.from_user.id,
        final_answer=final_answer,
        was_edited=False,
    )

    if ticket.message_log:
        try:
            await bot.send_message(
                chat_id=ticket.message_log.chat_id,
                text=final_answer,
                reply_to_message_id=ticket.message_log.telegram_msg_id,
            )
            logger.info("Sent approved answer to courier", chat_id=ticket.message_log.chat_id)
        except Exception:
            try:
                await bot.send_message(
                    chat_id=ticket.message_log.chat_id,
                    text=final_answer,
                )
            except Exception as e:
                logger.error("Failed to send to courier", error=str(e))

    mod_name = query.from_user.full_name
    try:
        await query.message.edit_text(
            text=query.message.html_text + f"\n\n✅ <b>ОДОБРЕНО</b> (@{query.from_user.username or mod_name})",
            parse_mode="HTML",
            reply_markup=None,
        )
        await query.answer("Ответ одобрен и отправлен курьеру!")
    except Exception as e:
        logger.error("Failed to update card", error=str(e))

    try:
        await rlhf_service.add_approved_knowledge(
            question=ticket.message_log.raw_text if ticket.message_log else "",
            answer=final_answer,
            language=ticket.courier.language if ticket.courier else "ru",
            ticket_id=str(ticket.id),
        )
    except Exception as e:
        logger.error("RLHF skipped", error=str(e))


@moderator_router.callback_query(ModeratorAction.filter(F.action == "edit"))
async def handle_start_edit_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    session: AsyncSession,
) -> None:
    if not query.message or not query.from_user:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_by_id(ticket_id)

    if not ticket or ticket.status not in ("pending", "waiting_edit", "waiting_confirm"):
        await query.answer("Тикет уже обработан.", show_alert=True)
        return

    await ticket_repo.set_waiting_edit(ticket_id=ticket_id, moderator_tg_id=query.from_user.id)

    _pending_edit[query.from_user.id] = str(ticket_id)
    logger.info("Stored pending edit in memory", moderator_id=query.from_user.id, ticket_id=str(ticket_id))

    try:
        await query.message.edit_text(
            text=query.message.html_text + "\n\n✏️ <i>(Ожидается ввод нового текста ответа...)</i>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass

    await query.message.reply("✏️ Отправьте новым сообщением исправленный текст ответа курьеру:")
    await query.answer()


@moderator_router.message()
async def handle_receive_edited_text(
    message: Message,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Catches any text from moderator chat — shows confirmation preview before sending to courier."""
    if not message.text or not message.from_user or message.text.startswith("/"):
        return

    # Check chat ID matching explicitly in function body
    if str(message.chat.id) != str(settings.moderator_chat_id):
        return

    moderator_id = message.from_user.id
    logger.info("Received message in moderator chat", user_id=moderator_id, text=message.text)
    ticket_repo = TicketRepository(session)

    # 1. Try in-memory store first
    ticket_id_str = _pending_edit.get(moderator_id)
    ticket = None

    if ticket_id_str:
        ticket = await ticket_repo.get_by_id(uuid.UUID(ticket_id_str))
        logger.info("Found ticket from memory", ticket_id=ticket_id_str)

    # 2. Fallback: query DB for active unanswered ticket
    if not ticket:
        ticket = await ticket_repo.get_active_unanswered_ticket()
        logger.info("Found ticket from active DB fallback", ticket_id=str(ticket.id) if ticket else None)

    # 3. Ultimate fallback: get absolute latest ticket in system
    if not ticket:
        ticket = await ticket_repo.get_latest_ticket()
        logger.info("Found ticket from ultimate DB fallback", ticket_id=str(ticket.id) if ticket else None)

    if not ticket:
        logger.info("No ticket found in database at all")
        return

    edited_answer = message.text

    # Update ticket in DB
    ticket.final_answer = edited_answer
    ticket.status = "waiting_confirm"

    # Clear in-memory store
    _pending_edit.pop(moderator_id, None)

    safe_text = html.escape(edited_answer)
    confirm_card_text = (
        f"📋 <b>ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР ОТВЕТА КУРЬЕРУ:</b>\n\n"
        f"<i>«{safe_text}»</i>\n\n"
        f"Отправить этот текст курьеру?"
    )

    try:
        await message.reply(
            text=confirm_card_text,
            reply_markup=get_confirm_send_keyboard(str(ticket.id)),
            parse_mode="HTML",
        )
        logger.info("Sent HTML preview card with button to moderator chat")
    except Exception as e:
        logger.error("Failed to send HTML preview card, falling back to plain text", error=str(e))
        plain_card_text = (
            f"📋 ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР ОТВЕТА КУРЬЕРУ:\n\n"
            f"«{edited_answer}»\n\n"
            f"Отправить этот текст курьеру?"
        )
        await message.reply(
            text=plain_card_text,
            reply_markup=get_confirm_send_keyboard(str(ticket.id)),
        )


@moderator_router.callback_query(ModeratorAction.filter(F.action == "confirm_send"))
async def handle_confirm_send_edited(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if not query.from_user or not query.message:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_by_id(ticket_id)

    if not ticket or not ticket.final_answer:
        await query.answer("Ошибка: Текст ответа не найден.", show_alert=True)
        return

    final_answer = ticket.final_answer

    await ticket_repo.update_status(
        ticket_id=ticket_id,
        status="edited",
        moderator_tg_id=query.from_user.id,
        final_answer=final_answer,
        was_edited=True,
    )

    if ticket.message_log:
        try:
            await bot.send_message(
                chat_id=ticket.message_log.chat_id,
                text=final_answer,
                reply_to_message_id=ticket.message_log.telegram_msg_id,
            )
            logger.info("Sent confirmed answer to courier", chat_id=ticket.message_log.chat_id)
        except Exception:
            try:
                await bot.send_message(
                    chat_id=ticket.message_log.chat_id,
                    text=final_answer,
                )
                logger.info("Sent confirmed answer to courier without reply_to", chat_id=ticket.message_log.chat_id)
            except Exception as e:
                logger.error("Failed to send to courier", error=str(e))

    mod_name = query.from_user.full_name
    try:
        await query.message.edit_text(
            text=(
                f"🚀 <b>ОТВЕТ ОТПРАВЛЕН КУРЬЕРУ</b> (@{query.from_user.username or mod_name})\n\n"
                f"<b>Текст:</b> <i>«{html.escape(final_answer)}»</i>"
            ),
            parse_mode="HTML",
            reply_markup=None,
        )
        await query.answer("Ответ успешно отправлен!")
    except Exception:
        await query.message.edit_text(
            text=(
                f"🚀 ОТВЕТ ОТПРАВЛЕН КУРЬЕРУ (@{query.from_user.username or mod_name})\n\n"
                f"Текст: «{final_answer}»"
            ),
            reply_markup=None,
        )
        await query.answer("Ответ успешно отправлен!")

    try:
        await rlhf_service.add_approved_knowledge(
            question=ticket.message_log.raw_text if ticket.message_log else "",
            answer=final_answer,
            language=ticket.courier.language if ticket.courier else "ru",
            ticket_id=str(ticket.id),
        )
    except Exception as e:
        logger.error("RLHF skipped", error=str(e))


@moderator_router.callback_query(ModeratorAction.filter(F.action == "reedit"))
async def handle_reedit_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    session: AsyncSession,
) -> None:
    if not query.message or not query.from_user:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    await ticket_repo.set_waiting_edit(ticket_id=ticket_id, moderator_tg_id=query.from_user.id)

    _pending_edit[query.from_user.id] = str(ticket_id)

    await query.message.edit_text(
        text="✏️ Введите новый исправленный текст ответа курьеру:",
        reply_markup=None,
    )
    await query.answer()


@moderator_router.callback_query(ModeratorAction.filter(F.action == "cancel"))
async def handle_cancel_edit_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    session: AsyncSession,
) -> None:
    if not query.message or not query.from_user:
        return

    ticket_id = uuid.UUID(callback_data.ticket_id)
    ticket_repo = TicketRepository(session)
    ticket = await ticket_repo.get_by_id(ticket_id)
    if ticket:
        ticket.status = "pending"

    _pending_edit.pop(query.from_user.id, None)

    await query.message.edit_text(
        text="❌ Отменено. Тикет возвращён.",
        reply_markup=get_moderator_ticket_keyboard(str(ticket_id)),
    )
    await query.answer("Отменено.")
