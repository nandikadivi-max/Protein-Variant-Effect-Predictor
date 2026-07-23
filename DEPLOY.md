# Deployment

The stack is designed to cost ~$0 when idle. This guide covers a Cloud Run +
Neon + Upstash + GCS + Vercel deployment. Everything account-specific is
called out; the code is already deploy-ready (see the Phase 7 commits).

## Architecture

| Component | Runs on | Idle cost |
|---|---|---|
| API (FastAPI, no torch) | Cloud Run, scale-to-zero | $0 |
| Worker (ARQ + ESM-2, 2.2GB CPU image) | Cloud Run, **min-instances 1** | see note |
| Postgres | Neon (serverless) | $0 |
| Redis (queue) | Upstash (serverless, TLS) | $0 |
| Matrices + structures | GCS bucket | ~cents |
| Frontend (Next.js) | Vercel | $0 |

**The one real cost — the worker.** The warm-model design (ESM-2 loaded once,
kept in RAM) needs an always-on process, which is incompatible with
scale-to-zero. Options, cheapest first:
- Cloud Run worker with `--min-instances=1 --cpu=2 --memory=4Gi --no-cpu-throttling`
  (always-on; small monthly cost).
- A free-tier always-on host (Fly.io / Oracle Always Free VM) running the
  worker image, pointed at the same Neon/Upstash/GCS.
- Accept a cold start: `--min-instances=0` + a scheduler that pings the
  worker; the first job after idle eats the ~20s model load. Only sane if the
  worker also serves the enqueue trigger, which ARQ doesn't — so not
  recommended here.

## Prerequisites

Accounts: Google Cloud (billing enabled), Neon, Upstash, Vercel. Tools:
`gcloud`, `docker`, `alembic` (in the local venv).

```bash
gcloud auth login && gcloud config set project YOUR_PROJECT
gcloud services enable run.googleapis.com artifactregistry.googleapis.com
REGION=us-central1
```

## 1. GCS bucket

```bash
gcloud storage buckets create gs://YOUR_BUCKET --location=$REGION
```

## 2. Neon Postgres + migrations

Create a project at neon.tech, copy the connection string, then run the
migrations from your machine (Alembic uses the sync driver + `sslmode=require`
automatically when `DB_REQUIRE_SSL=true`):

```bash
export DATABASE_URL="postgresql+asyncpg://USER:PASS@ep-xxx.REGION.aws.neon.tech/DB"
export DB_REQUIRE_SSL=true
alembic upgrade head
```

## 3. Upstash Redis

Create a database at upstash.com, copy the `rediss://` URL (TLS — already
handled by `RedisSettings.from_dsn`).

## 4. Build + push images (Artifact Registry)

```bash
gcloud artifacts repositories create pvep --repository-format=docker --location=$REGION
REPO=$REGION-docker.pkg.dev/YOUR_PROJECT/pvep

docker build -f infra/Dockerfile.api    -t $REPO/api:latest .
docker build -f infra/Dockerfile.worker -t $REPO/worker:latest .   # CPU-only torch, 2.2GB
docker push $REPO/api:latest && docker push $REPO/worker:latest
```

## 5. Deploy the API (scale-to-zero)

Give the runtime service account `roles/storage.objectAdmin` on the bucket so
the GCS store works without a key file.

```bash
gcloud run deploy pvep-api --image $REPO/api:latest --region $REGION \
  --allow-unauthenticated --port 8000 \
  --set-env-vars "DATABASE_URL=...,DB_REQUIRE_SSL=true,REDIS_URL=rediss://...,\
MATRIX_STORAGE_BACKEND=gcs,MATRIX_STORAGE_BUCKET=YOUR_BUCKET,\
CORS_ORIGINS=https://your-frontend.vercel.app"
```

## 6. Deploy the worker (always-on)

```bash
gcloud run deploy pvep-worker --image $REPO/worker:latest --region $REGION \
  --no-allow-unauthenticated --min-instances 1 --cpu 2 --memory 4Gi \
  --no-cpu-throttling \
  --set-env-vars "DATABASE_URL=...,DB_REQUIRE_SSL=true,REDIS_URL=rediss://...,\
MATRIX_STORAGE_BACKEND=gcs,MATRIX_STORAGE_BUCKET=YOUR_BUCKET"
```

The worker serves a health 200 on `$PORT` (Cloud Run's startup probe) while
consuming jobs from Redis.

## 7. Frontend (Vercel)

Import the repo in Vercel, set the root to `frontend/`, and set
`NEXT_PUBLIC_API_BASE=https://pvep-api-XXXX.run.app/api/v1`. After the first
deploy, put the Vercel URL into the API's `CORS_ORIGINS` and redeploy the API.

## Notes

- **AlphaMissense** (~1.2GB SQLite) isn't in the images. To enable it in prod,
  bake it into the worker image or attach a volume and set
  `ALPHAMISSENSE_DB_PATH`. The app runs fine without it.
- **Storage backend** is a pure config swap — `MATRIX_STORAGE_BACKEND=gcs`
  switches both the matrix and structure stores to GCS with zero code change.
