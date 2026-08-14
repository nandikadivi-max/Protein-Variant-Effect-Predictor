# Protein Variant Effect Predictor — Project Context

Read this before making changes. It records the decisions that are load-bearing
and the mistakes already made, so they are not made twice.

## What this is

Zero-shot missense variant effect prediction with ESM-2, plus a Mol* 3D viewer,
a full L×20 effect map, DSSP structural context and clinical annotations.
Benchmarked against ProteinGym. A portfolio and research piece, so commit
history and code quality matter as much as behaviour.

**Owner:** Nandika Divi · `github.com/nandikadivi-max/Protein-Variant-Effect-Predictor`
**Live:** https://protein-variant-effect-predictor.vercel.app
**API:** https://pvep-api-755950833591.us-east1.run.app

## Status

Deployed and working. All phases complete. **110 tests** pass
(`pytest -m "not network and not integration"`), mypy and ruff clean.

Deliberately deferred, with the owner's agreement:
- **LLM-assisted input help** ("Tier 2") — revisit in a month or two. Tier 1,
  deterministic repair, is built and covers the overwhelming majority.
- **Popularity-ranked example chips.** No new tracking is needed when this is
  picked up: `JobService.create_or_reuse` writes a `Job` row on the cached path
  too, so `jobs` is already a complete request log. Filter to jobs created
  after 2026-08-13 — everything before that is development traffic.

## Non-negotiable architectural decisions

Each exists to prevent a specific class of bug. Do not refactor away without
discussing.

### 1. Compute once per protein, derive everything
One `(L, 20)` log-probability matrix per protein. The single score, the
heatmap, the per-residue 3D colouring and the percentile are all cheap
derivations of it (`domain/derive.py`). The cache key is
`(model_id, sequence_hash)` — never the mutation.

Scoring is **deterministic**: pinned checkpoint revision, `eval()` mode, no
sampling, positions masked independently. Re-running the same model on the
same sequence returns the same numbers, so there is no "recompute for a better
answer" — the cache is memoisation of a pure function, not an approximation.
The legitimate version of "score it again" is *a different model*, which the
cache key already accommodates.

### 2. One coordinate system
UniProt canonical numbering is the source of truth everywhere, converted to
0-based only at designated boundaries. This has bitten repeatedly:
- **Clinical names use mature-protein numbering.** Sickle-cell is famously
  E6V, but the initiator methionine makes it **E7V** here. Same for SOD1 A4V →
  **A5V**. Two example chips shipped wrong because of this.
- **Structure files number residues their own way.** See §5.

### 3. The API never imports torch
Inference sits behind the `Scorer` protocol (`domain/scoring.py`), whose only
implementation is `worker/scorers/esm2.py` — the sole file importing torch.
`AA_ORDER = "ACDEFGHIKLMNPQRSTVWY"` is frozen. Adding SaProt or ESM-C means one
new class. Hard Docker boundary: API ~550MB, worker ~2.2GB.

### 4. Two worker transports, one scoring core
`worker/scoring_job.py::run_scoring` is shared by:
- `worker/main.py` — ARQ, **pulls** from Redis. Local dev, model warm forever.
- `worker/http_app.py` — FastAPI `POST /score`, **pushed** by Cloud Tasks.
  Production. Scoring happens inside the request so Cloud Run can scale to
  zero. The model loads lazily on first use; loading in the lifespan risks
  failing the startup probe.

The API picks via `JOB_DISPATCH` (`arq` | `cloudtasks`) and depends only on the
`JobDispatcher` protocol. **Redis is not needed in production** — it is only a
transport; job state lives in Postgres.

`run_scoring` uses three short-lived DB sessions. Holding one across the model
run made Neon drop the connection mid-job and lose the work *after* paying for
it.

### 5. Structures: one per provider, chosen per request
`structures` is keyed `(sequence_hash, provider)`, so a protein holds its
AlphaFold model **and** an experimental PDB entry at once. Which one you see
follows what you searched (`structure_provider` on the resolve response,
`?provider=` on `/structures`), defaulting to AlphaFold for full-length
coverage.

Before this, `sequence_hash` alone was the key, so resolving a PDB id
overwrote the prediction **globally** — one visitor changed what everyone saw.

Numbering, which is the subtle part:
- **Colour by author numbering mapped through SIFTS**, never `label_seq_id`.
  In 1TUP the p53 DBD is `label_seq_id` 1–219 but UniProt 94–312, so reading
  `label_seq_id` painted every residue with one 93 positions away.
- The mutation marker must use the **same** mapping as the colour theme.
- Object storage keys are provider-scoped (`alphafold.pdb` / `rcsb.pdb`);
  a bare `pdb` key made the two structures overwrite each other's file.
- PDBe sometimes omits `author_residue_number` (1TUP does) and numbers only
  one chain of a multimer. Both are reconstructed in `sifts_client`.

## Scientific claims — keep these honest

Reviewed as a domain expert; two claims previously overreached.

- **Thresholds** (`DAMAGING_LLR_THRESHOLD = -5.50`,
  `TOLERATED_LLR_THRESHOLD = -1.33`) are calibrated for **90% agreement with
  AlphaMissense**, which is itself a predictor. That is *not* 90% clinical
  accuracy. Calibrating against DMS fitness instead labels TP53 R175H — an
  established hotspot — as tolerated, which is why AlphaMissense was chosen.
- **ProteinGym mean Spearman 0.447** is over **five** small assays spanning
  0.017–0.599, not the full ~200-assay benchmark. It shows the harness works;
  it is not a benchmark reproduction.
- **Multi-substitution scores are additive**, ignoring epistasis. Surfaced in
  the UI, and `percentile` is `None` for them because a summed LLR is not drawn
  from the single-substitution distribution.
- **AlphaFold models carry pLDDT** in the B-factor column; 29% of TP53's atoms
  are below 50. The viewer offers a Confidence mode — **only for predicted
  models**, since the same column in an experimental structure means atomic
  mobility, the inverse reading.
- **Zero-shot LLR misses aggregation phenotypes.** HBB E7V (sickle-cell)
  scores −3.76, 37th percentile, *uncertain*, against ClinVar's Pathogenic.
  TTR V50M is the same story. Both cause disease by aggregation rather than by
  destabilising the fold, and a model scoring evolutionary plausibility cannot
  see that. `Discordance` in `SingleScoreCard.tsx` explains the gap wherever
  the model and the databases disagree, keyed off the labels so it holds for
  any protein. The sickle-cell chip stays on purpose: swapping it for a
  variant that scores well would be cherry-picking.
- **Conservation is not pathogenicity.** SNCA A53T (familial Parkinson's)
  scores **+2.07**, a positive LLR, 1st percentile, *likely tolerated*. Not a
  bug: rat α-synuclein (P37377) carries threonine at 53 natively, so the model
  is correct that the residue is unremarkable. It is answering a different
  question from "does this cause human disease". Verify before "fixing" any
  variant that looks mis-scored this way.
- **Clinical significance can disagree with itself.** EBI returns one feature
  per *genomic* variant, so a substitution reachable by several codon changes
  carries several entries. TP53 P72R has a Benign one (rs1042522, carried by
  roughly a quarter of people) and a Pathogenic somatic one. Taking the most
  severe reported that common polymorphism as disease-causing.
  `_pick_significance` now returns "Conflicting interpretations" when calls
  disagree in direction; severity is the tiebreak only when they agree, so no
  other demo variant moved. A risk factor beside a benign call is not a
  conflict.
- Scores are against **UniProt canonical isoform** only.

## Layout

```
contracts/   Pydantic schemas shared by api + worker. No torch. Frozen contract.
domain/      Pure logic, no I/O: Scorer protocol, variant parsing, matrix
             derivation, percentile, input classification, repair suggestions.
api/         FastAPI. Never imports torch.
  services/    resolution, job dispatch, results, structures, annotations,
               catalog of already-scored proteins
worker/      The only place torch lives.
  scoring_job.py  the job body, shared by both transports
  scorers/esm2.py masked-marginal implementation
  features/dssp.py secondary structure + SASA, projected onto UniProt coords
db/          Models + Alembic migrations (head: 0004_structures_per_provider)
storage/     MatrixStore + StructureStore (local | GCS, swapped by config)
frontend/    Next.js 14 App Router
benchmark/   ProteinGym harness + threshold calibration
infra/       Dockerfiles + cloudbuild.yaml
```

`db/` and `storage/` are top-level so the worker can persist without importing
API-only code.

## Environment and gotchas

- Python 3.11.9 via pyenv, venv at `.venv/`. **Node 24** via nvm (system node
  is 25, so `nvm use` picks up `frontend/.nvmrc`). Moved off 20 on 2026-08-14:
  Vercel fails builds on Node 20 from 2026-10-01. `engines` in
  `frontend/package.json` is the binding setting — it overrides the Vercel
  dashboard, so the dashboard's bulk-upgrade button silently skips this
  project.
- **Never run `next build` while `next dev` is running** — it corrupts `.next`.
  Stop dev, `rm -rf .next`, rebuild.
- **Port 5432 is blocked on the owner's WiFi.** Alembic and any direct DB work
  need a phone hotspot; everything else (gcloud, Docker, Cloud Build) is 443
  and fine. Batch DB work into one tethered session.
- **Build images with Cloud Build**, never locally: the laptop is arm64 and
  Cloud Run needs amd64. `gcloud builds submit --config infra/cloudbuild.yaml .`
  `.gcloudignore` keeps the context at 0.2MB; without it, 3.7GB is uploaded.
- **DSSP needs no binary.** `mkdssp` 4.x aborts without the ~800MB wwPDB
  chemical dictionary and silently produced nothing in the container.
  Secondary structure is pure-Python (pydssp) + Biopython Shrake-Rupley.
- **AlphaMissense** (~1.2GB SQLite) is optional and gitignored; the app
  degrades gracefully without it.

## Operational limits

- Scoring costs **~1s per residue** on the 8-vCPU worker. A novel 400-residue
  protein takes minutes; the UI says so and estimates from length. Cloud Tasks
  caps a job at 30 minutes.
- Cloud Tasks: `maxAttempts=3`, `maxConcurrentDispatches=4`. It shipped with
  **100 retries**, where one timing-out job could have cost ~$17.
- Worker `--max-instances 2`, `--concurrency 1`, scale-to-zero. Idle cost ≈ $0.
- The demo proteins are pre-seeded (`scripts/seed_demo_cache.py`) so visitors
  never wake the worker.
- **`MAX_NEW_JOBS_PER_DAY=15`** caps novel scoring in a rolling 24h; over it,
  `POST /jobs` returns 429. Cache hits are checked *first* and are never
  counted or refused, so the chips, the catalogue and shared links keep
  working regardless. Set because the API must be public and scoring is the
  only expensive thing here: unthrottled, a worker pinned at max instances
  runs to roughly $1,100/month. Tighten on the running service with
  `gcloud run services update pvep-api --region us-east1
  --update-env-vars MAX_NEW_JOBS_PER_DAY=N` — no rebuild. `0` disables it.
  The seed script bypasses it entirely (it runs the worker path directly
  against the DB, never through the API).

## Known limitations

- DSSP features are computed once per protein from the full-length prediction,
  so viewing an experimental structure shows a track describing the AlphaFold
  model.
- The impact colouring does not itself down-weight low-confidence regions; the
  Confidence toggle makes that inspectable rather than solving it.
- Substitutions only, ≤1022 residues (ESM-2 context limit). Deliberate v1 scope.

## Testing

```bash
pytest -m "not network and not integration"   # fast: 110 tests
pytest -m network                             # real UniProt/EBI/RCSB
pytest -m "integration and network"           # needs Postgres + Redis
pytest worker/scorers/test_esm2_smoke.py -s   # the correctness check that matters
```

The smoke test asserts TP53 R175H scores strongly damaging (−5.97) while the
conservative K372R does not (−0.10). If position or token indexing in the
scorer ever breaks, this is what catches it.

**Test the negative paths.** Every serious bug in this project was found off
the happy path — malformed input, boundary positions, hostile URLs, unusual but
legitimate formats — not by clicking the demo buttons. Check the *cost*
consequence of a bad request, not only its status code.
