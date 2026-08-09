import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.message_log import MessageLog


class MessageLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log_message(
        self,
        courier_id: uuid.UUID,
        telegram_msg_id: int,
        chat_id: int,
        raw_text: str,
        detected_language: str | None = None,
        intent_label: str | None = None,
        intent_confidence: float | None = None,
        rag_score: float | None = None,
        was_auto_replied: bool = False,
    ) -> MessageLog:
        """Create a new message log entry."""
        log = MessageLog(
            courier_id=courier_id,
            telegram_msg_id=telegram_msg_id,
            chat_id=chat_id,
            raw_text=raw_text,
            detected_language=detected_language,
            intent_label=intent_label,
            intent_confidence=intent_confidence,
            rag_score=rag_score,
            was_auto_replied=was_auto_replied,
        )
        self._session.add(log)
        await self._session.flush()
        await self._session.refresh(log)
        return log
