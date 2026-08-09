import structlog
from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import settings

logger = structlog.get_logger()

db_url = str(settings.database_url)
if db_url.startswith("postgresql"):
    try:
        engine: AsyncEngine = create_async_engine(
            "sqlite+aiosqlite:///./courier.db",
            echo=False,
            connect_args={"timeout": 30.0},
        )
        logger.info("Using SQLite with WAL mode for local testing (courier.db)")
    except Exception as e:
        logger.warning("Falling back to SQLite", error=str(e))
        engine = create_async_engine(
            "sqlite+aiosqlite:///./courier.db",
            echo=False,
            connect_args={"timeout": 30.0},
        )
else:
    engine = create_async_engine(db_url, echo=False)


# Enable WAL mode for SQLite to prevent 'database is locked' errors
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
