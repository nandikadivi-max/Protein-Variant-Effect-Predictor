"""
Budget kill-switch: the last line of defence on cost.

Cloud Billing budgets only send mail. This turns one into something that
actually acts, because the deployment is left unattended for long stretches
and an alert nobody reads stops nothing.

The response is graduated on purpose. Disabling billing is genuinely
destructive -- Cloud Run stops, the GCS bucket becomes unreachable, and
everything needs manual re-enabling -- so it is the second thing tried, not
the first:

    >= SOFT_BRAKE_RATIO (default 50%)   set MAX_NEW_JOBS_PER_DAY=0 on the API.
                                        Worker spend goes to zero while the
                                        site stays completely up: every cached
                                        protein, the examples and the
                                        catalogue all keep working. Scoring is
                                        the only thing that costs real money,
                                        so this alone should stop the bleeding.

    >= 100%                             detach the billing account. Everything
                                        stops. Only reached if the soft brake
                                        failed or something nobody predicted is
                                        spending money.

In practice the soft brake should mean the hard stop never fires.

Two failure modes are designed around:

  * Budget notifications repeat every time cost data refreshes, so both
    actions check current state first. Without that, a week over the soft
    threshold would pile up a Cloud Run revision per notification.

  * A failure in the soft brake must never prevent the hard stop, so it is
    wrapped. The expensive mistake is silently doing nothing.
"""

import base64
import json
import os

import functions_framework
import google.auth
from googleapiclient import discovery

PROJECT_ID = os.environ["TARGET_PROJECT"]
REGION = os.environ.get("TARGET_REGION", "us-east1")
API_SERVICE = os.environ.get("TARGET_SERVICE", "pvep-api")
SOFT_BRAKE_RATIO = float(os.environ.get("SOFT_BRAKE_RATIO", "0.5"))

CAP_ENV_VAR = "MAX_NEW_JOBS_PER_DAY"
BRAKE_VALUE = "0"  # 0 means "score nothing new" (see config.Settings)


@functions_framework.cloud_event
def on_budget_notification(cloud_event) -> None:
    payload = json.loads(base64.b64decode(cloud_event.data["message"]["data"]))

    cost = float(payload.get("costAmount") or 0)
    budget = float(payload.get("budgetAmount") or 0)
    currency = payload.get("currencyCode", "")
    if budget <= 0:
        print("no budget amount in notification, ignoring")
        return

    ratio = cost / budget
    print(
        f"budget '{payload.get('budgetDisplayName', '?')}': "
        f"{cost:.2f}/{budget:.2f} {currency} = {ratio:.1%}"
    )

    if ratio >= 1.0:
        print("at or over budget -- disabling billing")
        disable_billing()
        return

    if ratio >= SOFT_BRAKE_RATIO:
        try:
            apply_soft_brake()
        except Exception as exc:  # never let this mask the hard stop
            print(f"soft brake failed, hard stop still armed: {exc!r}")
        return

    print("under the soft threshold, nothing to do")


def apply_soft_brake() -> None:
    """Stop scoring novel proteins; leave everything cached serving."""
    creds, _ = google.auth.default()
    run = discovery.build(
        "run",
        "v1",
        credentials=creds,
        cache_discovery=False,
        client_options={"api_endpoint": f"https://{REGION}-run.googleapis.com"},
    )
    name = f"namespaces/{PROJECT_ID}/services/{API_SERVICE}"
    service = run.namespaces().services().get(name=name).execute()

    container = service["spec"]["template"]["spec"]["containers"][0]
    env = container.setdefault("env", [])
    for entry in env:
        if entry.get("name") == CAP_ENV_VAR:
            if entry.get("value") == BRAKE_VALUE:
                print("soft brake already applied, leaving it alone")
                return
            entry["value"] = BRAKE_VALUE
            break
    else:
        env.append({"name": CAP_ENV_VAR, "value": BRAKE_VALUE})

    # Cloud Run rejects a replace that reuses an explicit revision name, and
    # generates a fresh one when it is absent.
    service["spec"]["template"]["metadata"].pop("name", None)
    run.namespaces().services().replaceService(name=name, body=service).execute()
    print(f"SOFT BRAKE APPLIED: {CAP_ENV_VAR}={BRAKE_VALUE} on {API_SERVICE}")


def disable_billing() -> None:
    """Detach the billing account. Everything in the project stops."""
    creds, _ = google.auth.default()
    billing = discovery.build(
        "cloudbilling", "v1", credentials=creds, cache_discovery=False
    )
    name = f"projects/{PROJECT_ID}"

    info = billing.projects().getBillingInfo(name=name).execute()
    if not info.get("billingEnabled"):
        print("billing already disabled, nothing to do")
        return

    billing.projects().updateBillingInfo(
        name=name, body={"billingAccountName": ""}
    ).execute()
    print(f"BILLING DISABLED on {PROJECT_ID} -- all services stopped")
