"""
Pre-score a set of proteins straight into the production cache.

Why this exists
---------------
In production the worker scales to zero, so the first request for an
unscored protein pays a cold start (instance boot + ~40s ESM-2 load +
scoring). That is fine for a curious visitor exploring a novel protein,
but it is a bad first impression for the handful of proteins a demo
actually lands on.

The matrix cache makes that avoidable. A protein that already has a
`score_matrices` row is served entirely by the API — Postgres for the
row, object storage for the `.npz` — and never touches the worker at
all (see `JobService.create_or_reuse`). So if the demo proteins are
seeded ahead of time, the common path is fast *and* the worker stays
scaled to zero.

This script runs the worker's own scoring path locally against whatever
`DATABASE_URL` / `MATRIX_STORAGE_*` point at. Point it at production and
your laptop becomes a one-off worker:

    export DATABASE_URL="postgresql+asyncpg://...@...neon.tech/neondb"
    export DB_REQUIRE_SSL=true
    export MATRIX_STORAGE_BACKEND=gcs
    export MATRIX_STORAGE_BUCKET=your-bucket
    python scripts/seed_demo_cache.py

Already-cached proteins are skipped, so it is safe to re-run.
"""

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select

from api.services.protein_resolver import ProteinResolver
from api.services.sifts_client import SiftsClient
from api.services.structure_client import StructureClient
from api.services.structure_service import StructureService
from api.services.uniprot_client import UniProtClient
from config import get_settings
from db.models import Job, ScoreMatrix
from db.session import async_session_factory
from storage.structure_store import get_structure_store

# Proteins worth having warm: recognisable to a biologist, each with a
# well-known pathogenic variant to point at in the UI, and spanning several
# disease areas so the demo does not look cancer-only.
#
# Every entry MUST be <= domain.scoring.MAX_SEQUENCE_LENGTH (1022). That rules
# out several obvious candidates — BRCA1 (1863), EGFR (1210), PIK3CA (1068) —
# which is why the oncogene slot is KRAS rather than one of those.
DEFAULT_TARGETS = [
    "P04637",  # TP53  (393) — R175H, the classic DNA-binding-domain hotspot
    "P01116",  # KRAS  (189) — G12D, the most-mutated oncogene
    "P60484",  # PTEN  (403) — tumour suppressor
    "P06400",  # RB1   (928) — retinoblastoma; the long end of the range
    "P00441",  # SOD1  (154) — A4V, familial ALS
    "P37840",  # SNCA  (140) — A53T, Parkinson's
    "P02766",  # TTR   (147) — V30M, hereditary amyloidosis
    "P68871",  # HBB   (147) — E6V, sickle-cell
    "P0DP23",  # CALM1 (149) — calmodulin; tiny and ultra-conserved
    "P01308",  # INS   (110) — insulin; smallest, good first demo
]


async def seed_one(scorer, raw_input: str) -> str:
    """Resolve, score, persist. Returns a short status string for the log."""
    from worker.scorers.esm2 import DEFAULT_REVISION
    from worker.scoring_job import run_scoring

    settings = get_settings()
    model_id = settings.default_model_id

    async with async_session_factory() as session:
        uniprot = UniProtClient()
        sifts = SiftsClient()
        struct_client = StructureClient()
        try:
            resolver = ProteinResolver(
                session=session,
                uniprot=uniprot,
                sifts=sifts,
                structures=StructureService(
                    session=session,
                    store=get_structure_store(),
                    client=struct_client,
                ),
            )
            protein = await resolver.resolve(raw_input)
        finally:
            await uniprot.aclose()
            await sifts.aclose()
            await struct_client.aclose()

        seq_hash = protein.sequence_hash

        existing = await session.execute(
            select(ScoreMatrix).where(
                ScoreMatrix.sequence_hash == seq_hash,
                ScoreMatrix.model_id == model_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return f"cached already ({len(protein.sequence)} aa)"

        # run_scoring expects a job row to move through its lifecycle.
        job_id = str(uuid.uuid4())
        session.add(
            Job(
                job_id=job_id,
                sequence_hash=seq_hash,
                model_id=model_id,
                status="queued",
            )
        )
        await session.commit()

    await run_scoring(
        scorer,
        job_id=job_id,
        sequence_hash=seq_hash,
        model_id=model_id,
        model_revision=DEFAULT_REVISION,
    )
    return f"scored ({len(protein.sequence)} aa)"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets",
        nargs="*",
        default=DEFAULT_TARGETS,
        help="UniProt accessions, gene names, or PDB IDs. Defaults to the demo set.",
    )
    args = parser.parse_args()

    settings = get_settings()
    print(f"Storage backend : {settings.matrix_storage_backend}")
    print(f"Database        : {settings.database_url.split('@')[-1]}")
    print(f"Targets         : {len(args.targets)}\n")

    # Loading the model is the expensive part — do it once for all targets.
    from worker.scorers.esm2 import ESM2Scorer

    print("Loading ESM-2 650M...")
    scorer = ESM2Scorer()
    print(f"Loaded on {scorer.device}\n")

    failures = 0
    for i, target in enumerate(args.targets, 1):
        prefix = f"[{i}/{len(args.targets)}] {target:<10}"
        try:
            status = await seed_one(scorer, target)
            print(f"{prefix} {status}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{prefix} FAILED: {exc!r}")

    print(f"\nDone. {len(args.targets) - failures} succeeded, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
