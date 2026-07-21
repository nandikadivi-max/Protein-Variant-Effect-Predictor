"""
FastAPI entrypoint. This process NEVER imports torch — that boundary is
what keeps this image thin and fast to boot. All model inference happens
in the worker process; this tier only resolves, validates, enqueues, and
serves cached results.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import create_arq_pool
from api.routes import jobs, proteins, results, structures


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis pool for ARQ is a per-process singleton, held on app.state.
    app.state.arq_pool = await create_arq_pool()
    yield
    await app.state.arq_pool.close()


app = FastAPI(
    title="Protein Variant Effect Predictor API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(proteins.router, prefix="/api/v1", tags=["proteins"])
app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
app.include_router(results.router, prefix="/api/v1", tags=["results"])
app.include_router(structures.router, prefix="/api/v1", tags=["structures"])
