# Budget kill-switch

A Cloud Billing budget only sends mail. This turns one into something that
acts, because the deployment is left unattended for long stretches and an
alert nobody reads stops nothing.

## What happens, and when

The budget is **$15/month** on project `protein-variant-eff-predictor`, with
notifications going to the `pvep-budget-alerts` Pub/Sub topic. The function
computes `costAmount / budgetAmount` itself, so it responds to the real ratio
rather than to which threshold rule happened to fire.

| Spend | Action | Site |
|---|---|---|
| < 50% | nothing | normal |
| ≥ 50% | `MAX_NEW_JOBS_PER_DAY=0` on `pvep-api` | **fully up** — everything cached still serves; only novel scoring is refused, with a 429 that explains itself |
| ≥ 100% | billing detached from the project | **everything stops** |

The soft brake exists because scoring is the only thing that costs real money,
so stopping it should stop the bleeding without anyone losing the demo. The
hard stop is the backstop for something nobody predicted.

A failure in the soft brake never prevents the hard stop — it is wrapped, and
the failure is logged. Silently doing nothing is the expensive mistake.

Both actions check current state first. Budget notifications repeat every time
cost data refreshes, so without that a week over the soft threshold would pile
up one Cloud Run revision per notification.

## Testing it safely

Publish a synthetic notification. **Keep the ratio under 1.0** unless you
actually want billing disabled:

```bash
gcloud pubsub topics publish pvep-budget-alerts \
  --project protein-variant-eff-predictor \
  --message='{"budgetDisplayName":"test","costAmount":9.0,"budgetAmount":15.0,"currencyCode":"USD"}'
```

That is 60%, so it exercises the soft brake and the whole Pub/Sub → function →
Cloud Run path without touching billing. Undo with:

```bash
gcloud run services update pvep-api --region us-east1 \
  --update-env-vars MAX_NEW_JOBS_PER_DAY=15
```

The 100% path is deliberately left untested. It is one API call and its
failure mode is loud.

## Recovering after a hard stop

Billing being detached stops Cloud Run and makes the GCS bucket unreachable.
Nothing is deleted immediately, but do not leave it sitting.

```bash
# 1. reattach billing
gcloud billing projects link protein-variant-eff-predictor \
  --billing-account=0195F2-74BD52-FAECE9

# 2. clear whatever caused it, then lift the soft brake
gcloud run services update pvep-api --region us-east1 \
  --update-env-vars MAX_NEW_JOBS_PER_DAY=15

# 3. confirm both services came back
gcloud run services list --region us-east1
```

If matrices in GCS were lost, `scripts/seed_demo_cache.py` rebuilds the demo
cache from scratch.

## IAM

The function runs as `pvep-killswitch@…iam.gserviceaccount.com`:

| Role | Why |
|---|---|
| `roles/billing.projectManager` (**on the project**, not the billing account) | detach billing. Granting it on the billing account is rejected — the permission that matters lives on the project |
| `roles/run.admin` | read and replace the `pvep-api` service |
| `roles/iam.serviceAccountUser` on the runtime SA | replacing a Cloud Run service requires `actAs` on the account it runs as |
| `roles/artifactregistry.reader` | **not obvious**: Cloud Run resolves and validates the image on replace, so without it every soft brake fails with a 403 about `artifactregistry.repositories.downloadArtifacts`. Found by testing; `run.admin` alone is not enough |

## Redeploying

```bash
gcloud functions deploy pvep-budget-killswitch \
  --gen2 --runtime python311 --region us-east1 \
  --source infra/killswitch \
  --entry-point on_budget_notification \
  --trigger-topic pvep-budget-alerts \
  --service-account pvep-killswitch@protein-variant-eff-predictor.iam.gserviceaccount.com \
  --set-env-vars TARGET_PROJECT=protein-variant-eff-predictor,TARGET_REGION=us-east1,TARGET_SERVICE=pvep-api,SOFT_BRAKE_RATIO=0.5 \
  --memory 256Mi --timeout 120s
```
