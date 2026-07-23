"""
Async engine and session factory. Import `get_session` from here in
services that need a database session. Never create engines ad-hoc.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_settings

settings = get_settings()

# Managed Postgres (Neon etc.) requires TLS. asyncpg enables SSL when passed
# ssl=True (uses the default verifying context); local dev leaves it off.
_connect_args = {"ssl": True} if settings.db_require_ssl else {}

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency + generic async iterator for scripts/tests."""
    async with async_session_factory() as session:
        yield session
