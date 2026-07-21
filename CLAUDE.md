# Protein Variant Effect Predictor — Project Context

This file is read automatically by Claude Code. It captures the full
project state as of the handoff from chat-based planning to Claude Code
development. Read this before making changes.

## What this project is

A research-oriented protein variant effect predictor: given a protein and
a mutation (e.g. TP53 R175H), predict whether the mutation is damaging,
using zero-shot ESM-2 scoring. Includes an interactive 3D structure
viewer (Mol*) and a full variant-effect heatmap. Benchmarked against
ProteinGym. Built as a portfolio/research project for recruiter and
professor showcases — code quality and commit history matter, not just
functionality.

**Owner:** Nandika Divi. Repo: `github.com/nandikadivi-max/Protein-Variant-Effect-Predictor`

## Non-negotiable architectural decisions

These were deliberated at length and are frozen. Do not refactor away
from them without discussing first — each one exists to prevent a
specific class of bug or a specific late-stage rewrite.

### 1. Compute once per protein, derive everything
ESM-2 masked-marginal scoring produces one `(L, 20)` log-probability
matrix per protein. Every product — single mutation score, full L×20
heatmap, per-residue 3D coloring — is a cheap derivation of that one
matrix (`domain/derive.py`). The cache key is `(model_id, sequence_hash)`,
not the mutation. A protein is scored exactly once per model, ever.

### 2. One coordinate system
UniProt canonical numbering (1-based, converted to 0-based only at the
two designated boundary points) is the single source of truth for every
position. AlphaFold structures are UniProt-numbered by default. PDB
structures require an explicit SIFTS map (not yet implemented — deferred
to the structure pipeline phase). Never let a mutation string, a scored
position, and a 3D-colored residue silently refer to different numbering
schemes.

### 3. Async from day one, warm model singleton
The API process **never imports torch**. A separate ARQ worker process
loads ESM-2 once at startup (`worker/main.py` `startup()`) and stays warm
across jobs. This is a hard Docker image boundary — see "Process boundary"
below.

### The `Scorer` protocol (anti-refactor centerpiece)
`domain/scoring.py` defines a `Scorer` Protocol with one method:
`per_position_log_probs(sequence) -> (L, 20) ndarray`. `worker/scorers/esm2.py`
is the only implementation right now and the **only file in the whole
repo that imports torch**. Adding SaProt, ESM C, or an ensemble later
means writing a new class satisfying this protocol — zero changes to any
caller. `AA_ORDER = "ACDEFGHIKLMNPQRSTVWY"` is frozen; every scorer must
gather its output into exactly this column order.

## Tech stack (locked)

- **Frontend:** Next.js/React/TypeScript, Tailwind, shadcn/ui, Framer Motion, Mol* for 3D
- **Backend:** FastAPI (async, never imports torch)
- **Worker:** ARQ (async Redis queue), holds ESM-2 warm in a module singleton
- **ML:** PyTorch + Hugging Face Transformers, ESM-2 650M (`facebook/esm2_t33_650M_UR50D`, MIT licensed, not gated)
- **DB:** PostgreSQL via SQLAlchemy 2.0 async + Alembic migrations
- **Queue/cache:** Redis
- **Matrix storage:** pluggable `MatrixStore` protocol — `LocalMatrixStore` (filesystem, active) and `GCSMatrixStore` (Google Cloud Storage, implemented but unused until deploy)
- **Bioinformatics:** Biopython, DSSP (not yet wired), UniProt REST API, AlphaFold DB, RCSB PDB
- **Design direction:** scientific & minimalistic — light neutral background, `Inter` (UI) + `JetBrains Mono` (sequences/mutations), restrained diverging color scale (blue↔red) for the heatmap

## Environment (already set up and verified working)

- macOS, Apple Silicon
- Python 3.11.9 via pyenv (`pyenv local 3.11.9` set in repo root — do not use the `base` conda env)
- Node 20.20.2 via nvm
- Docker Desktop 29.6.2
- Homebrew 6.0.12
- Virtualenv at `.venv/` — activate with `source .venv/bin/activate`

Known environment gotcha already solved: pyenv-built Python needs `xz`
installed *before* compiling or `lzma` breaks (`brew install xz` then
`pyenv uninstall -f 3.11.9 && pyenv install 3.11.9`). Already fixed on
this machine — noting in case of a fresh machine setup later.

## Repository structure (as of last verified state)

```
/contracts        Pydantic schemas shared by api + worker. No torch. FROZEN API contract.
/domain           Pure business logic: scoring.py (Scorer protocol, AA_ORDER),
                   derive.py (matrix -> products), resolve.py (input classification,
                   sequence hashing). No torch, no I/O side effects. Fully unit tested.
/config.py         Top-level Settings (pydantic-settings), shared by api + worker.
/db                Top-level: SQLAlchemy models (proteins, score_matrices, structures,
                   jobs), async session factory, Alembic migrations. Shared by api + worker
                   — promoted out of api/ specifically so the worker can persist without
                   importing api-only code.
/storage           Top-level: MatrixStore protocol + LocalMatrixStore/GCSMatrixStore.
                   Promoted out of api/ for the same reason as db/.
/api               FastAPI app. NEVER imports torch.
  main.py          App entrypoint, lifespan (creates ARQ redis pool), route registration
  deps.py          Dependency-injection factories for all services
  routes/          proteins.py (resolve), jobs.py (create/poll), results.py (get scores)
  services/        uniprot_client.py (real UniProt REST calls), protein_resolver.py,
                   job_service.py (cache-hit logic — THE critical perf path),
                   results_service.py (reads matrix, computes derived products)
/worker            ARQ worker. The ONLY place torch/transformers/esm live.
  main.py          Warm ESM-2 singleton, score_job (loads sequence, scores, persists)
  scorers/esm2.py  ESM2Scorer — masked-marginal scoring implementation
  scorers/test_esm2_smoke.py  TP53 R175H correctness smoke test (see below — MUST verify)
/benchmark         Offline ProteinGym harness. NOT YET BUILT (Phase 7).
/frontend          Next.js app. NOT YET BUILT (Phase 6). package.json + tailwind.config.ts
                   scaffolded with design tokens only.
/infra             Dockerfile.api (thin, no torch), Dockerfile.worker (torch + DSSP)
/tests             test_end_to_end.py — in-process integration test exercising the full
                   resolve -> score -> persist -> read pipeline against real Postgres+Redis
docker-compose.yml  postgres, redis, api, worker services
alembic.ini         Points to db/migrations
.env.example        Copy to .env for local dev
```

## Current status — exactly where we left off

**Phases 1, 2, 3a, 3b are code-complete AND now fully verified running.**
Last verified test run (2026-07-20): **`30 passed`** — the ENTIRE suite,
including network, integration, and the ESM-2 smoke test, all green
together with `torch` installed.

**The whole backend has now been exercised for real, not just unit-tested:**
- Postgres + Redis up and healthy (docker compose), schema created
  (`alembic upgrade head`, at `0001_initial`, 4 tables present).
- `torch` 2.13.0 + `transformers` 5.14.1 installed via `.[worker]`.
- TP53 R175H smoke test **run and passing**: LLR = **−5.9744** (damaging),
  vs conservative K372R = −0.0982. Scorer position/token indexing is
  correct.
- Full in-process integration test passing (ubiquitin, L8P → LLR −8.97).
- **Real HTTP round trip done** through live `uvicorn` API + live `arq`
  worker + Redis + Postgres: resolve `P01308` (insulin) → job (queued,
  not cached) → worker scored → results (110×20 effect map, M1V LLR
  −6.02, `likely_damaging`). Cache-hit path confirmed over HTTP
  (`cached: true`, `status: done`, nothing re-queued). Matrix `.npz`
  files persisted under `data/matrices/`.

- **Containerized stack verified:** both Docker images build and run.
  Round trip through the real `api` + `worker` containers (78-aa FASTA →
  queued job → worker scored inside the container in ~15s → 78×20 map,
  K8P LLR −0.15, cache-hit confirmed). API image **543MB** (no torch,
  boundary intact), worker image **8.93GB** (torch + CUDA — see deploy
  note in "Immediate next steps").

Several fixes landed while getting this running (see "Known issues" below):
`greenlet` dependency, the async-engine test-loop conftest, and the
Dockerfile ordering + setuptools packaging fixes that made the images
build at all.

### What's fully built and tested
- Domain layer (`domain/`): `Scorer` protocol, `AA_ORDER`, sequence
  validation, `Variant` parsing (`R248Q`, multi-sub `R248Q:D281N`),
  matrix derivation math, input classification, sequence hashing/dedup.
  18 unit tests, all pass, no network/DB needed.
- Matrix storage (`storage/`): `LocalMatrixStore` fully tested (5 tests,
  round-trip write/read, sharding, existence checks). `GCSMatrixStore`
  implemented but never exercised — do so before relying on it.
- UniProt client (`api/services/uniprot_client.py`): verified against the
  **real** UniProt REST API (3 integration tests, marked
  `@pytest.mark.network`, all pass). Notably fixed a real bug here: gene
  search originally OR'd `gene_exact` with a loose `protein_name` match,
  which caused `TP53` to sometimes resolve to `TP53RK` (a different gene
  whose description contains the substring "TP53"). Now uses
  `gene_exact` only — precision over recall by design.
- ESM-2 scorer (`worker/scorers/esm2.py`): implemented, not yet run
  end-to-end (needs `pip install -e ".[worker]"`, ~2GB torch download).
  **The TP53 R175H smoke test in `worker/scorers/test_esm2_smoke.py` has
  never actually been executed** — the TP53 sequence was typed from
  memory and needs verification. This is the single most important
  correctness check in the codebase (a hotspot cancer mutation MUST
  score as damaging, or something is wrong with position/token indexing).
  **Run this before trusting anything downstream of the scorer.**
- API routes: all 5 endpoints registered and verified via OpenAPI schema
  introspection (`POST /api/v1/proteins/resolve`, `POST /api/v1/jobs`,
  `GET /api/v1/jobs/{id}`, `GET /api/v1/results/{sequence_hash}`,
  `GET /health`). Never hit with a real request yet — needs Postgres +
  Redis running.
- Worker (`worker/main.py`): real `score_job` implementation (not
  stubbed), loads sequence from DB, scores, persists matrix + DB row,
  updates job status. **Never actually run** — needs the full stack up.

### What's explicitly NOT built yet
- ~~AlphaFold/RCSB structure fetching~~ **DONE (Phase 4a):** StructureStore,
  StructureClient (AlphaFold via prediction API + RCSB), StructureService,
  and `GET /structures/{hash}` + `/file` endpoints. Verified end to end.
- PDB ID resolution (`ProteinResolver._resolve` raises `NotImplementedError`
  for `pdb_id` classification — **Phase 4b, next**, ships with the SIFTS
  UniProt-numbering map)
- DSSP structural features (secondary structure, RSA, contact maps) —
  Phase 4c; runs in the worker (has the `dssp` binary) and populates the
  already-defined `StructureContext` contract
- AlphaMissense / ClinVar annotation lookups — Phase 4d
- Frontend — nothing beyond `package.json` and `tailwind.config.ts` scaffolding
- ProteinGym benchmark harness
- Score label calibration (currently hardcoded placeholder thresholds
  in `api/services/results_service.py`: `DAMAGING_LLR_THRESHOLD = -3.0`,
  `TOLERATED_LLR_THRESHOLD = -0.5` — these are NOT calibrated against
  real data yet, that's Phase 7)
- Deployment (Cloud Run, GCS bucket, Neon Postgres) — decided Cloud Run +
  possibly Neon for Postgres (to get true scale-to-zero, avoid Cloud
  SQL's ~$10/mo idle cost) but not yet set up

## Immediate next steps (resume here)

Steps 1–7 of the old resume checklist are **DONE and verified**, AND the
full containerized stack is now proven too (schema, torch install, smoke
test, integration test, a local HTTP round trip, AND a round trip through
the actual `api` + `worker` Docker images — see "Current status" above).
What remains:

1. **Deploy prep (image size):** the worker image is **8.93GB** because
   the linux torch wheel pulls in CUDA/cuDNN libs that Cloud Run's CPU
   will never use. Before deploy, install CPU-only torch in
   `infra/Dockerfile.worker` via
   `pip install --index-url https://download.pytorch.org/whl/cpu torch ...`
   — should cut the image to ~2–3GB. (API image is already a lean 543MB.)
2. **Phase 4:** structure pipeline — PDB ID resolution (currently
   `NotImplementedError`), AlphaFold/RCSB fetch, DSSP structural features
   (secondary structure, RSA, contacts), AlphaMissense/ClinVar lookups.
3. **Phase 5:** frontend (Next.js — only scaffolding exists today).
4. **Phase 6:** ProteinGym benchmark harness + score-label calibration
   (the `DAMAGING/TOLERATED_LLR_THRESHOLD` placeholders are still
   uncalibrated).
5. **Phase 7:** deploy (Cloud Run + Neon Postgres + GCS bucket).

To restart the local stack for a manual HTTP round trip:
```bash
docker compose up -d postgres redis          # if not already up
source .venv/bin/activate
arq worker.main.WorkerSettings &             # loads ESM-2 warm
uvicorn api.main:app --port 8000 &
# then: POST /api/v1/proteins/resolve -> POST /api/v1/jobs
#       -> GET /api/v1/jobs/{id} -> GET /api/v1/results/{hash}?mutation=...
```

## Testing reference

```bash
# Fast, no network, no DB — run constantly during development
pytest -m "not network and not integration" -v

# Hits real UniProt API
pytest -m network -v

# Needs docker compose up -d postgres redis + alembic upgrade head first
pytest -m "integration and network" -v -s

# The one correctness check that matters most — run after any scorer change
pytest worker/scorers/test_esm2_smoke.py -v -s
```

Pytest markers are registered in `pyproject.toml` under `[tool.pytest.ini_options]`.

## Design decisions worth remembering

- **Storage backend:** currently `local` (filesystem, `./data/matrices`)
  for dev. `GCSMatrixStore` exists and is a drop-in swap via
  `MATRIX_STORAGE_BACKEND=gcs` + `MATRIX_STORAGE_BUCKET` env vars — no
  code changes needed when we deploy.
- **Billing approach:** Cloud Run has no idle cost. Cloud SQL does
  (~$10/mo always-on). Plan is to use Neon (serverless Postgres, scales
  to zero) instead of Cloud SQL specifically so the project costs $0
  when not being actively demoed to recruiters/professors. Not yet
  implemented — still on local Postgres via docker-compose.
- **Commit history matters** — this is a portfolio piece professors and
  recruiters may look at. Commit incrementally with meaningful messages
  (`feat: add ESM-2 scorer`, `fix: gene search false-positive on
  substring match`, etc.), not one giant final commit.
- **Substitutions only in v1** — no indels, sequences capped at 1022
  residues (`domain/scoring.py` `MAX_SEQUENCE_LENGTH`). This is a
  deliberate scope decision, not an oversight.

## Known issues to watch for

- ~~The ESM-2 smoke test's hardcoded TP53 sequence was typed from memory
  and never verified.~~ **RESOLVED (2026-07-20):** fetched real UniProt
  P04637 FASTA and diffed — the hardcoded sequence is an **exact match**
  (393 residues, position 175 = R, position 372 = K). The smoke test's
  pass/fail is now trustworthy.
- **Stray duplicate file:** `test_esm2_smoke.py` exists BOTH at the repo
  root and at `worker/scorers/test_esm2_smoke.py` — byte-identical. The
  root copy is a download-mishap artifact (see the note two bullets down);
  it is NOT in `testpaths` so pytest never collects it, but it's a trap.
  Safe to delete the root-level one; the canonical copy is under
  `worker/scorers/`.
- **`greenlet` dependency (FIXED):** SQLAlchemy's async extension needs
  `greenlet`, but `pyproject.toml` declared plain `sqlalchemy>=2.0.0`, so
  it wasn't installed and every async DB call failed with "the greenlet
  library is required". Now declared as `sqlalchemy[asyncio]>=2.0.0`.
- **Async-engine test-loop lifecycle (FIXED):** `db/session.py` `engine`
  is a module-level singleton with a connection pool, but pytest-asyncio
  gives each test its own event loop. A pooled connection from one test
  was closed during a later test's loop → "RuntimeError: Event loop is
  closed". Fixed with `tests/conftest.py` (autouse fixture that calls
  `await engine.dispose()` after each test). Production is unaffected —
  the API/worker each run one long-lived loop where pooling is correct.
- **Dockerfile build order + packaging (FIXED):** both Dockerfiles ran
  `pip install -e .` BEFORE copying the source, so the editable install
  had no packages to discover and failed. Separately, `pyproject.toml`
  had an *explicit* package list including every subdir — incompatible
  with the split images (thin API has no `worker/`; worker has no
  `api/routes`). Fixed by (a) reordering both Dockerfiles to copy source
  before install, and (b) switching to `[tool.setuptools.packages.find]`
  with `include` globs so discovery adapts to whatever source each image
  copies. Also added `.dockerignore` (was missing — the whole `.venv`
  was being shipped as build context).
- **CUDA image bloat (KNOWN, not yet fixed):** worker image is 8.93GB
  because the default linux torch wheel bundles CUDA libs unused on CPU.
  See deploy note #1 in "Immediate next steps" for the CPU-only fix.
- **No `.gitignore` existed (FIXED):** the repo had no `.gitignore` at
  all, so `.env` (dev password), `.venv/`, and generated `data/` were
  not actually being ignored despite `.env.example` claiming otherwise.
  Added a proper one.
- `results_service.py` classification thresholds
  (`DAMAGING_LLR_THRESHOLD`, `TOLERATED_LLR_THRESHOLD`) are placeholder
  values, not calibrated against ProteinGym yet. Don't present these as
  scientifically meaningful until Phase 7 calibration is done.
- Two file-download mishaps happened during setup where zip contents
  landed in `~/Downloads/<name>/` instead of the repo, causing stale
  code to silently persist. If something seems to not be taking effect
  after an edit, check for duplicate/stale files before assuming the
  logic is wrong.
