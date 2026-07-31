# Deployment

This deploys to **~$0/month at idle**. Everything scales to zero, including
the ESM-2 worker.

## Architecture

| Component | Runs on | Idle cost |
|---|---|---|
| API (FastAPI, no torch) | Cloud Run, scale-to-zero | $0 |
| Worker (ESM-2, 2.2GB CPU image) | Cloud Run, **scale-to-zero** | $0 |
| Job dispatch | Cloud Tasks | $0 (1M/mo free) |
| Postgres | Neon (serverless) | $0 |
| Matrices + structures | GCS bucket | ~$0.02 |
| Frontend (Next.js) | Vercel | $0 |
| Redis | **not needed in production** | — |

### How the worker scales to zero

Cloud Run only allocates CPU while a request is in flight. A pull-based
worker (ARQ polling Redis) therefore *cannot* scale to zero — there is no
request to scale on, so it must run 24/7 with `--no-cpu-throttling`, which is
the expensive configuration. Instead:

```
POST /jobs → API creates job row → Cloud Tasks → worker POST /score
                                                  (scores in-request,
                                                   then scales to 0)
```

`JOB_DISPATCH=cloudtasks` selects this path
([job_dispatcher.py](api/services/job_dispatcher.py)). Local dev keeps the ARQ
path (`JOB_DISPATCH=arq`) so the model stays warm across repeated runs. Both
share the same scoring core in [worker/scoring_job.py](worker/scoring_job.py).

Redis is only a job *transport* — job state lives in Postgres — so the Cloud
Tasks path needs no Redis instance at all.

### The cold-start trade-off, and how to hide it

A scaled-to-zero worker means the first request for an **unscored** protein
pays ~60–90s (instance boot + ESM-2 load + scoring). Repeat requests for an
**already-scored** protein never touch the worker at all — the API serves them
from Postgres + GCS in milliseconds.

So seed the demo proteins ahead of time (step 7). After that, everything a
visitor is likely to click is instant and the worker stays asleep.

---

## Prerequisites

Accounts: Google Cloud (billing enabled), Neon, Vercel. Tools: `gcloud`,
`docker`, and the local venv.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
    cloudtasks.googleapis.com storage.googleapis.com
```

Set these once for the rest of the guide:

```bash
export PROJECT=YOUR_PROJECT
export REGION=us-central1
export BUCKET=YOUR_BUCKET
```

## 1. GCS bucket

```bash
gcloud storage buckets create gs://$BUCKET --location=$REGION
```

## 2. Neon Postgres + migrations

Create a project at [neon.tech](https://neon.tech) and copy the connection
string. Convert it to the asyncpg form and strip any `?sslmode=` query arg —
`DB_REQUIRE_SSL=true` handles TLS for both the async and Alembic drivers:

```bash
export DATABASE_URL="postgresql+asyncpg://USER:PASS@ep-xxx.REGION.aws.neon.tech/neondb"
export DB_REQUIRE_SSL=true
alembic upgrade head
```

## 3. Service account + Cloud Tasks queue

The queue needs an identity allowed to invoke the private worker service.

```bash
gcloud iam service-accounts create pvep-tasks \
    --display-name="Cloud Tasks -> worker invoker"
export TASKS_SA=pvep-tasks@$PROJECT.iam.gserviceaccount.com

gcloud tasks queues create pvep-jobs --location=$REGION
```

## 4. Build + push images

```bash
gcloud artifacts repositories create pvep \
    --repository-format=docker --location=$REGION
gcloud auth configure-docker $REGION-docker.pkg.dev
export REPO=$REGION-docker.pkg.dev/$PROJECT/pvep

docker build -f infra/Dockerfile.api    -t $REPO/api:latest .
docker build -f infra/Dockerfile.worker -t $REPO/worker:latest .
docker push $REPO/api:latest && docker push $REPO/worker:latest
```

> Build for `linux/amd64`. On Apple Silicon add `--platform linux/amd64` to
> both builds, or Cloud Run will reject the arm64 image.

## 5. Deploy the worker (scale-to-zero, private)

Deploy the worker first — the API needs its URL.

```bash
gcloud run deploy pvep-worker --image $REPO/worker:latest --region $REGION \
  --no-allow-unauthenticated \
  --min-instances 0 --cpu 2 --memory 4Gi --concurrency 1 --timeout 1800 \
  --set-env-vars "WORKER_MODE=http,DATABASE_URL=$DATABASE_URL,DB_REQUIRE_SSL=true,\
MATRIX_STORAGE_BACKEND=gcs,MATRIX_STORAGE_BUCKET=$BUCKET"

export WORKER_URL=$(gcloud run services describe pvep-worker \
    --region $REGION --format='value(status.url)')
```

`--concurrency 1` keeps one scoring job per instance (ESM-2 is memory-hungry
and CPU-bound; two concurrent jobs would thrash). `--timeout 1800` covers a
cold model load plus a long sequence.

Let the queue's identity invoke it, and let the runtime write to GCS:

```bash
export PROJNUM=$(gcloud projects describe $PROJECT --format='value(projectNumber)')

gcloud run services add-iam-policy-binding pvep-worker --region $REGION \
    --member="serviceAccount:$TASKS_SA" --role=roles/run.invoker

gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
    --member="serviceAccount:$PROJNUM-compute@developer.gserviceaccount.com" \
    --role=roles/storage.objectAdmin
```

## 6. Deploy the API (scale-to-zero, public)

```bash
gcloud run deploy pvep-api --image $REPO/api:latest --region $REGION \
  --allow-unauthenticated --min-instances 0 \
  --set-env-vars "DATABASE_URL=$DATABASE_URL,DB_REQUIRE_SSL=true,\
MATRIX_STORAGE_BACKEND=gcs,MATRIX_STORAGE_BUCKET=$BUCKET,\
JOB_DISPATCH=cloudtasks,GCP_PROJECT=$PROJECT,CLOUD_TASKS_LOCATION=$REGION,\
CLOUD_TASKS_QUEUE=pvep-jobs,CLOUD_TASKS_SERVICE_ACCOUNT=$TASKS_SA,\
WORKER_URL=$WORKER_URL,CORS_ORIGINS=https://your-frontend.vercel.app"
```

The API's runtime identity needs permission to create tasks, and to mint
OIDC tokens as the queue's service account:

```bash
gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:$PROJNUM-compute@developer.gserviceaccount.com" \
    --role=roles/cloudtasks.enqueuer

gcloud iam service-accounts add-iam-policy-binding $TASKS_SA \
    --member="serviceAccount:$PROJNUM-compute@developer.gserviceaccount.com" \
    --role=roles/iam.serviceAccountUser
```

## 7. Seed the demo cache

Run the worker's scoring path locally, writing straight into the production
database and bucket. Takes a few minutes on a laptop; makes every demo
protein load instantly forever after.

```bash
source .venv/bin/activate
gcloud auth application-default login

export DATABASE_URL DB_REQUIRE_SSL=true
export MATRIX_STORAGE_BACKEND=gcs MATRIX_STORAGE_BUCKET=$BUCKET

python scripts/seed_demo_cache.py
```

Pass your own targets to seed more:
`python scripts/seed_demo_cache.py TP53 BRCA2 1CRN`.

## 8. Frontend (Vercel)

Import the repo, set the root directory to `frontend/`, and set:

```
NEXT_PUBLIC_API_BASE=https://pvep-api-XXXX.run.app/api/v1
```

After the first deploy, put the real Vercel URL into the API's `CORS_ORIGINS`
and redeploy the API.

---

## Verifying

```bash
export API=$(gcloud run services describe pvep-api --region $REGION \
    --format='value(status.url)')

curl -s $API/health
curl -s -X POST $API/api/v1/proteins/resolve \
    -H 'Content-Type: application/json' -d '{"input":"P04637"}'
```

A seeded protein should come back from `POST /api/v1/jobs` with
`"cached": true` and `"status": "done"` — no worker involved.

To watch a cold start, resolve something unseeded and tail the worker:

```bash
gcloud run services logs tail pvep-worker --region $REGION
```

## Notes

- **AlphaMissense** (~1.2GB SQLite) is not in the images. To enable it in
  production, bake it into the API image or mount a volume and set
  `ALPHAMISSENSE_DB_PATH`. The app degrades gracefully without it.
- **Staying at $0:** the only metered resources are GCS storage (cents),
  Cloud Run request-seconds (the free tier covers 180k vCPU-seconds/month),
  and Cloud Tasks (1M dispatches free). A demo getting a few hundred visits a
  month stays free.
- **If you later want zero cold starts**, redeploy the worker with
  `WORKER_MODE=arq`, `--min-instances 1`, `--no-cpu-throttling` and a Redis
  URL, and set the API back to `JOB_DISPATCH=arq`. No code changes — but
  expect a real monthly bill for the always-allocated CPU.
