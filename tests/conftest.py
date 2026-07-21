"""
Test fixtures scoped to the integration tests in this directory.

pytest-asyncio (asyncio_mode=auto) gives each test its own function-scoped
event loop, but `db.session.engine` is a module-level singleton with a
connection pool. A connection opened during one test's loop would otherwise
be handed back to the pool and closed during a *later* test's loop, and
asyncpg's graceful close schedules work on the originating loop — which is
already gone by then ("RuntimeError: Event loop is closed").

Disposing the engine after every test closes all pooled connections while
the loop that created them is still alive, so nothing leaks across loops.
Production code is unaffected: the API and worker each run a single
long-lived loop where pooling is exactly what we want.
"""

import pytest_asyncio

from db.session import engine


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()
