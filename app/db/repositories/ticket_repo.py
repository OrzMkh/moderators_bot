from datetime import datetime, timezone
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.ticket import Ticket


class TicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_ticket(
        self,
        message_log_id: uuid.UUID,
        courier_id: uuid.UUID,
        draft_answer: str,
    ) -> Ticket:
        """Create a pending moderator ticket."""
        ticket = Ticket(
            message_log_id=message_log_id,
            courier_id=courier_id,
            draft_answer=draft_answer,
            status="pending",
        )
        self._session.add(ticket)
        await self._session.flush()
        await self._session.refresh(ticket)
        return ticket

    async def get_by_id(self, ticket_id: uuid.UUID) -> Ticket | None:
        """Fetch ticket with message_log and courier relations."""
        stmt = (
            select(Ticket)
            .where(Ticket.id == ticket_id)
            .options(
                selectinload(Ticket.message_log),
                selectinload(Ticket.courier),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_waiting_edit_ticket(self, moderator_tg_id: int) -> Ticket | None:
        """Fetch ticket waiting for edit input (matches waiting_edit status or latest pending)."""
        # First try exact match for this moderator's waiting_edit ticket
        stmt = (
            select(Ticket)
            .where(Ticket.status == "waiting_edit", Ticket.moderator_tg_id == moderator_tg_id)
            .options(
                selectinload(Ticket.message_log),
                selectinload(Ticket.courier),
            )
            .order_by(Ticket.created_at.desc())
        )
        result = await self._session.execute(stmt)
        ticket = result.scalars().first()
        if ticket:
            return ticket

        # Fallback: get latest pending or waiting_edit ticket in DB
        stmt_fallback = (
            select(Ticket)
            .where(Ticket.status.in_(["waiting_edit", "pending"]))
            .options(
                selectinload(Ticket.message_log),
                selectinload(Ticket.courier),
            )
            .order_by(Ticket.created_at.desc())
        )
        result_fallback = await self._session.execute(stmt_fallback)
        return result_fallback.scalars().first()

    async def set_waiting_edit(self, ticket_id: uuid.UUID, moderator_tg_id: int) -> Ticket | None:
        """Mark ticket as waiting for moderator edit input."""
        ticket = await self.get_by_id(ticket_id)
        if not ticket:
            return None

        ticket.status = "waiting_edit"
        ticket.moderator_tg_id = moderator_tg_id
        await self._session.flush()
        return ticket

    async def update_status(
        self,
        ticket_id: uuid.UUID,
        status: str,
        moderator_tg_id: int,
        final_answer: str | None = None,
        was_edited: bool = False,
        moderator_chat_msg_id: int | None = None,
    ) -> Ticket | None:
        """Update ticket resolution status."""
        ticket = await self.get_by_id(ticket_id)
        if not ticket:
            return None

        ticket.status = status
        ticket.moderator_tg_id = moderator_tg_id
        ticket.was_edited = was_edited
        ticket.resolved_at = datetime.now(timezone.utc)
        if final_answer:
            ticket.final_answer = final_answer
        if moderator_chat_msg_id:
            ticket.moderator_chat_msg_id = moderator_chat_msg_id

        await self._session.flush()
        return ticket
