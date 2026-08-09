import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, GUID


class MessageLog(Base):
    __tablename__ = "message_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
    )
    courier_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("couriers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_msg_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    detected_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    intent_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    intent_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rag_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    was_auto_replied: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # Relationships
    courier: Mapped["Courier"] = relationship("Courier", back_populates="message_logs")
    ticket: Mapped["Ticket | None"] = relationship("Ticket", back_populates="message_log", uselist=False)
