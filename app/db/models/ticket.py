import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, GUID


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
    )
    message_log_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("message_logs.id", ondelete="CASCADE"),
        nullable=False,
    )
    courier_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("couriers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        index=True,
    )
    draft_answer: Mapped[str] = mapped_column(Text, nullable=False)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    moderator_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    moderator_chat_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    was_edited: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    rlhf_vectorized: Mapped[bool] = mapped_column(
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
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    message_log: Mapped["MessageLog"] = relationship("MessageLog", back_populates="ticket")
    courier: Mapped["Courier"] = relationship("Courier", back_populates="tickets")
