import structlog
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import settings

logger = structlog.get_logger()

db_url = str(settings.database_url)

# Build the engine based on configured DB URL
if "postgresql" in db_url or "postgres" in db_url:
    # Use real PostgreSQL on Render (persistent storage)
    # Convert psycopg2 URLs to asyncpg format if needed
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and "asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine: AsyncEngine = create_async_engine(
        db_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
    )
    logger.info("Using PostgreSQL database", url=db_url[:40])
else:
    # Local development fallback: SQLite with WAL
    from sqlalchemy import event

    engine = create_async_engine(
        "sqlite+aiosqlite:///./courier.db",
        echo=False,
        connect_args={"timeout": 30.0},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        finally:
            cursor.close()

    logger.info("Using SQLite database for local dev")


async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing asynchronous database sessions."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
