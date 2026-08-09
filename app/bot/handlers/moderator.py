import html
import uuid
import structlog
from aiogram import F, Router, Bot
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.ticket import Ticket
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
# Strict filter for messages: ONLY catch text updates originating from the moderator chat
moderator_router.message.filter(F.chat.id == settings.moderator_chat_id)

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

    try:
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

        courier_sent = False
        if ticket.message_log:
            try:
                await bot.send_message(
                    chat_id=ticket.message_log.chat_id,
                    text=final_answer,
                    reply_to_message_id=ticket.message_log.telegram_msg_id,
                )
                courier_sent = True
                logger.info("Sent approved answer to courier with reply", chat_id=ticket.message_log.chat_id)
            except Exception as e:
                logger.warning("Could not send with reply_to_message_id, trying direct send", error=str(e))
                try:
                    await bot.send_message(
                        chat_id=ticket.message_log.chat_id,
                        text=final_answer,
                    )
                    courier_sent = True
                except Exception as e2:
                    logger.error("Failed to send directly to courier chat", error=str(e2))

        if not courier_sent:
            try:
                await bot.send_message(
                    chat_id=settings.supergroup_id,
                    text=final_answer,
                )
                logger.info("Sent approved answer to fallback supergroup")
            except Exception as e3:
                logger.error("Fallback supergroup send failed", error=str(e3))

        mod_name = query.from_user.full_name
        try:
            current_text = query.message.html_text or query.message.text or ""
            await query.message.edit_text(
                text=current_text + f"\n\n✅ <b>ОДОБРЕНО</b> (@{query.from_user.username or mod_name})",
                parse_mode="HTML",
                reply_markup=None,
            )
            await query.answer("Ответ одобрен и отправлен курьеру!")
        except Exception as e:
            logger.error("Failed to update card", error=str(e))
            await query.answer("Ответ отправлен курьеру!")

        try:
            await rlhf_service.add_approved_knowledge(
                question=ticket.message_log.raw_text if ticket.message_log else "",
                answer=final_answer,
                language=ticket.courier.language if ticket.courier else "ru",
                ticket_id=str(ticket.id),
            )
        except Exception as e:
            logger.error("RLHF skipped", error=str(e))
    except Exception as e:
        logger.error("Error in handle_approve_ticket", error=str(e))
        await query.answer("Произошла ошибка при обработке.", show_alert=True)


@moderator_router.callback_query(ModeratorAction.filter(F.action == "edit"))
async def handle_start_edit_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    session: AsyncSession,
) -> None:
    if not query.message or not query.from_user:
        return

    try:
        ticket_id = uuid.UUID(callback_data.ticket_id)
        ticket_repo = TicketRepository(session)
        ticket = await ticket_repo.get_by_id(ticket_id)

        if ticket:
            await ticket_repo.set_waiting_edit(ticket_id=ticket_id, moderator_tg_id=query.from_user.id)

        _pending_edit[query.from_user.id] = str(callback_data.ticket_id)
        logger.info("Stored pending edit in memory", moderator_id=query.from_user.id, ticket_id=callback_data.ticket_id)

        try:
            current_text = query.message.html_text or query.message.text or ""
            await query.message.edit_text(
                text=current_text + "\n\n✏️ <i>(Ожидается ввод нового текста ответа...)</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass

        await query.message.reply("✏️ Отправьте новым сообщением исправленный текст ответа курьеру:")
        await query.answer()
    except Exception as e:
        logger.error("Error in handle_start_edit_ticket", error=str(e))


@moderator_router.message(F.text & ~F.text.startswith("/"))
async def handle_receive_edited_text(
    message: Message,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Catches any text from moderator chat — shows confirmation preview before sending to courier."""
    if not message.text or not message.from_user:
        return

    moderator_id = message.from_user.id
    logger.info("Received message in moderator chat", user_id=moderator_id, text=message.text)

    edited_answer = message.text
    ticket_id_target = _pending_edit.get(moderator_id)

    ticket = None
    ticket_repo = TicketRepository(session)

    try:
        if ticket_id_target:
            try:
                ticket = await ticket_repo.get_by_id(uuid.UUID(ticket_id_target))
            except Exception:
                ticket = None

        if not ticket and message.reply_to_message:
            ticket = await ticket_repo.get_by_moderator_msg_id(message.reply_to_message.message_id)

        if not ticket:
            ticket = await ticket_repo.get_active_unanswered_ticket()

        if not ticket:
            ticket = await ticket_repo.get_latest_ticket()

        if ticket:
            ticket.final_answer = edited_answer
            ticket.status = "waiting_confirm"
            ticket_id_target = str(ticket.id)
            await session.flush()
    except Exception as e:
        logger.error("Database operation failed in handle_receive_edited_text", error=str(e))

    # Clear pending edit memory
    _pending_edit.pop(moderator_id, None)

    if not ticket_id_target:
        ticket_id_target = str(uuid.uuid4())

    safe_text = html.escape(edited_answer)
    confirm_card_text = (
        f"📋 <b>ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР ОТВЕТА КУРЬЕРУ:</b>\n\n"
        f"<i>«{safe_text}»</i>\n\n"
        f"Отправить этот текст курьеру?"
    )

    try:
        await message.reply(
            text=confirm_card_text,
            reply_markup=get_confirm_send_keyboard(ticket_id_target),
            parse_mode="HTML",
        )
        logger.info("SUCCESS: Sent preview card with button to moderator chat!")
    except Exception as e:
        logger.error("Failed to send HTML preview card, sending plain text card", error=str(e))
        plain_card_text = (
            f"📋 ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР ОТВЕТА КУРЬЕРУ:\n\n"
            f"«{edited_answer}»\n\n"
            f"Отправить этот текст курьеру?"
        )
        await message.reply(
            text=plain_card_text,
            reply_markup=get_confirm_send_keyboard(ticket_id_target),
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

    try:
        ticket_id = uuid.UUID(callback_data.ticket_id)
        ticket_repo = TicketRepository(session)
        ticket = await ticket_repo.get_by_id(ticket_id)

        final_answer = ticket.final_answer if (ticket and ticket.final_answer) else query.message.text or ""

        if ticket:
            await ticket_repo.update_status(
                ticket_id=ticket_id,
                status="edited",
                moderator_tg_id=query.from_user.id,
                final_answer=final_answer,
                was_edited=True,
            )

        # 1. Send answer to Courier Supergroup / Chat
        courier_sent = False
        if ticket and ticket.message_log:
            try:
                await bot.send_message(
                    chat_id=ticket.message_log.chat_id,
                    text=final_answer,
                    reply_to_message_id=ticket.message_log.telegram_msg_id,
                )
                courier_sent = True
                logger.info("Sent edited answer to courier with reply", chat_id=ticket.message_log.chat_id)
            except Exception as e:
                logger.warning("Failed to send with reply_to_message_id, trying direct send", error=str(e))
                try:
                    await bot.send_message(
                        chat_id=ticket.message_log.chat_id,
                        text=final_answer,
                    )
                    courier_sent = True
                except Exception as e2:
                    logger.error("Failed to send to courier", error=str(e2))

        if not courier_sent:
            try:
                await bot.send_message(
                    chat_id=settings.supergroup_id,
                    text=final_answer,
                )
                logger.info("Sent answer directly to supergroup_id fallback")
            except Exception as e:
                logger.error("Supergroup fallback send failed", error=str(e))

        # 2. Update Card in Moderator Chat
        mod_name = query.from_user.full_name
        safe_answer = html.escape(final_answer)
        try:
            await query.message.edit_text(
                text=(
                    f"🚀 <b>ОТВЕТ ОТПРАВЛЕН КУРЬЕРУ</b> (@{query.from_user.username or mod_name})\n\n"
                    f"<b>Текст:</b> <i>«{safe_answer}»</i>"
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

        # 3. RLHF
        if ticket:
            try:
                await rlhf_service.add_approved_knowledge(
                    question=ticket.message_log.raw_text if ticket.message_log else "",
                    answer=final_answer,
                    language=ticket.courier.language if ticket.courier else "ru",
                    ticket_id=str(ticket.id),
                )
            except Exception as e:
                logger.error("RLHF skipped", error=str(e))

    except Exception as e:
        logger.error("Error in handle_confirm_send_edited", error=str(e))
        await query.answer("Произошла ошибка при отправке.", show_alert=True)


@moderator_router.callback_query(ModeratorAction.filter(F.action == "reedit"))
async def handle_reedit_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    session: AsyncSession,
) -> None:
    if not query.message or not query.from_user:
        return

    _pending_edit[query.from_user.id] = str(callback_data.ticket_id)

    try:
        await query.message.edit_text(
            text="✏️ Введите новый исправленный текст ответа курьеру:",
            reply_markup=None,
        )
        await query.answer()
    except Exception as e:
        logger.error("Error in reedit", error=str(e))


@moderator_router.callback_query(ModeratorAction.filter(F.action == "cancel"))
async def handle_cancel_edit_ticket(
    query: CallbackQuery,
    callback_data: ModeratorAction,
    session: AsyncSession,
) -> None:
    if not query.message or not query.from_user:
        return

    _pending_edit.pop(query.from_user.id, None)

    try:
        await query.message.edit_text(
            text="❌ Отменено. Тикет возвращён в очередь.",
            reply_markup=get_moderator_ticket_keyboard(str(callback_data.ticket_id)),
        )
        await query.answer("Отменено.")
    except Exception as e:
        logger.error("Error in cancel", error=str(e))
