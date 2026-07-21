"""
FastAPI dependency-injection factories. Every service that a route
handler needs is constructed here per-request, taking a DB session and
whatever singletons (Redis pool, matrix store) live at app-level.
"""

from collections.abc import AsyncIterator

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.alphamissense_provider import AlphaMissenseProvider
from api.services.annotation_client import AnnotationClient
from api.services.annotation_service import AnnotationService
from api.services.job_service import JobService
from api.services.protein_resolver import ProteinResolver
from api.services.results_service import ResultsService
from api.services.sifts_client import SiftsClient
from api.services.structure_client import StructureClient
from api.services.structure_service import StructureService
from api.services.uniprot_client import UniProtClient
from config import get_settings
from db.session import async_session_factory
from storage.matrix_store import get_matrix_store
from storage.structure_store import get_structure_store


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def get_arq(request: Request) -> ArqRedis:
    """Redis pool is created once at app startup and shared."""
    return request.app.state.arq_pool


async def create_arq_pool() -> ArqRedis:
    settings = get_settings()
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))


async def get_uniprot() -> AsyncIterator[UniProtClient]:
    client = UniProtClient()
    try:
        yield client
    finally:
        await client.aclose()


async def get_resolver(
    session: AsyncSession = Depends(get_db),
    uniprot: UniProtClient = Depends(get_uniprot),
) -> AsyncIterator[ProteinResolver]:
    sifts = SiftsClient()
    struct_client = StructureClient()
    try:
        structures = StructureService(
            session=session, store=get_structure_store(), client=struct_client
        )
        yield ProteinResolver(
            session=session, uniprot=uniprot, sifts=sifts, structures=structures
        )
    finally:
        await sifts.aclose()
        await struct_client.aclose()


def get_job_service(
    session: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq),
) -> JobService:
    return JobService(session=session, arq=arq)


async def get_results_service(
    session: AsyncSession = Depends(get_db),
) -> AsyncIterator[ResultsService]:
    # Structure features are read from the store (no client). Annotations do
    # hit the EBI Proteins API, so that client needs closing.
    structures = StructureService(session=session, store=get_structure_store())
    annotation_client = AnnotationClient()
    try:
        yield ResultsService(
            session=session,
            matrix_store=get_matrix_store(),
            structures=structures,
            annotations=AnnotationService(
                annotation_client, alphamissense=AlphaMissenseProvider()
            ),
        )
    finally:
        await annotation_client.aclose()


async def get_structure_service(
    session: AsyncSession = Depends(get_db),
) -> AsyncIterator[StructureService]:
    client = StructureClient()
    try:
        yield StructureService(
            session=session, store=get_structure_store(), client=client
        )
    finally:
        await client.aclose()
