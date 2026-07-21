# Protein Variant Effect Predictor

Zero-shot protein variant effect prediction using ESM-2 masked-marginal
scoring, with an interactive 3D structure viewer and variant effect
heatmap. Benchmarked against ProteinGym.

## Architecture

See `ARCHITECTURE.md` (in the project's design docs) for the full system
design. Summary of the load-bearing decisions:

- **Compute once per protein**: a single `(L, 20)` score matrix is computed
  per (protein, model) pair and cached forever. Every mutation query, the
  full heatmap, and the 3D coloring are all cheap derivations of that one
  matrix.
- **One coordinate system**: UniProt canonical numbering is the source of
  truth for every position, everywhere.
- **Async from day one**: the API tier never imports `torch`. A separate
  worker process holds the model warm and processes jobs from a queue.

## Repository layout

```
/contracts   Pydantic schemas shared by api + worker. No torch.
/domain      Pure business logic: resolve.py, scoring.py, derive.py. No torch.
/api         FastAPI app. Never imports torch.
/worker      ARQ worker + ESM-2 scorer. The ONLY place torch lives.
/benchmark   Offline ProteinGym evaluation harness.
/frontend    Next.js app.
/infra       Dockerfiles.
```

## Local development setup

### Prerequisites
- Python 3.11 (`pyenv local 3.11.9` — already set for this repo)
- Node 20 LTS
- Docker Desktop

### Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"       # for api/domain work
pip install -e ".[worker]"    # additionally, if working on the scorer
```

### Run the full stack locally

```bash
docker compose up --build
```

This starts Postgres, Redis, the API (port 8000), and the worker. First
worker boot will download ESM-2 650M (~2.6 GB) — this is cached in the
`model_cache` volume so it only happens once.

### Run tests

Fast tests (pure domain logic, no model loading):
```bash
pytest domain/ contracts/ -v
```

Slow smoke test (loads the real model — proves scoring correctness):
```bash
pytest worker/scorers/test_esm2_smoke.py -v -s
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Build order

1. Domain layer + contracts (done — this scaffold)
2. ESM-2 scorer + TP53 R175H smoke test (done — this scaffold)
3. Worker persistence (Postgres + object storage) + job queue wiring
4. FastAPI endpoints against the frozen schemas
5. Structure + DSSP features; AlphaFold fetch; annotation lookups
6. Frontend: input → Mol* viewer → heatmap
7. ProteinGym benchmark harness; calibrate score labels
8. Polish + deploy
