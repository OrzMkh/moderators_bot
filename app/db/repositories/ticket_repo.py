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
