from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.courier import Courier


class CourierRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None = None,
        full_name: str | None = None,
        language: str = "ru",
    ) -> Courier:
        """Fetch courier by telegram_id or create a new one."""
        stmt = select(Courier).where(Courier.telegram_id == telegram_id)
        result = await self._session.execute(stmt)
        courier = result.scalar_one_or_none()

        if not courier:
            courier = Courier(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name,
                language=language,
            )
            self._session.add(courier)
            await self._session.flush()
            await self._session.refresh(courier)
        else:
            # Update last seen and profile if changed
            if username and courier.username != username:
                courier.username = username
            if full_name and courier.full_name != full_name:
                courier.full_name = full_name
            await self._session.flush()

        return courier
