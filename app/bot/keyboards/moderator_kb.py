from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class ModeratorAction(CallbackData, prefix="mod"):
    action: str  # "approve" | "edit"
    ticket_id: str


def get_moderator_ticket_keyboard(ticket_id: str) -> InlineKeyboardMarkup:
    """Generates inline keyboard for moderator ticket approval/edit."""
    builder_buttons = [
        [
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=ModeratorAction(action="approve", ticket_id=ticket_id).pack(),
            ),
            InlineKeyboardButton(
                text="✏️ Отредактировать",
                callback_data=ModeratorAction(action="edit", ticket_id=ticket_id).pack(),
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=builder_buttons)
