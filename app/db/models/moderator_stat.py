import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, Float, Integer, UniqueConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, GUID


class ModeratorStat(Base):
    __tablename__ = "moderator_stats"
    __table_args__ = (
        UniqueConstraint("moderator_tg_id", "date", name="uq_moderator_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
    )
    moderator_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        default=date.today,
    )
    approved_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    edited_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    avg_response_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
