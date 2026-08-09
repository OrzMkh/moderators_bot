import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, String, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, GUID

JSONType = JSONB().with_variant(JSON, "sqlite")


class Courier(Base):
    __tablename__ = "couriers"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True,
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    language: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ru",
        index=True,
    )  # 'ru', 'uz_cyr', 'uz_lat'
    service_type: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )  # 'food_delivery', 'logistics', 'bike_rental'
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType,
        nullable=False,
        default=dict,
    )

    # Relationships
    message_logs: Mapped[list["MessageLog"]] = relationship(
        "MessageLog", back_populates="courier", cascade="all, delete-orphan"
    )
    tickets: Mapped[list["Ticket"]] = relationship(
        "Ticket", back_populates="courier", cascade="all, delete-orphan"
    )
