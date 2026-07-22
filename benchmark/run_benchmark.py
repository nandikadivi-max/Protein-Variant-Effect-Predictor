"""
Offline ProteinGym benchmark runner.

Fetches ProteinGym DMS assays (cached under data/proteingym/), scores each
with ESM-2, and reports per-assay + mean Spearman — ProteinGym's headline
metric. Writes results.json (LLRs + DMS bins) for threshold calibration.

    python -m benchmark.run_benchmark                 # curated small set
    python -m benchmark.run_benchmark --assays IF1_ECOLI_Kelsic_2016 ...
    python -m benchmark.run_benchmark --limit 10      # 10 smallest single-mut

This imports torch (via the ESM-2 scorer) — it's an offline harness, not the
API. First run downloads the 650M model if not already cached.
"""

import argparse
import csv
import json
import urllib.request
from dataclasses import asdict
from pathlib import Path

HF = "https://huggingface.co/datasets/OATML-Markslab/ProteinGym/resolve/main"
REF_URL = f"{HF}/ProteinGym_reference_file_substitutions.csv"
ASSAY_URL = HF + "/ProteinGym_substitutions/{dms_id}.csv"

DATA_DIR = Path("data/proteingym")

# A small, diverse, single-mutant default set that scores quickly on CPU.
DEFAULT_ASSAYS = [
    "IF1_ECOLI_Kelsic_2016",       # 72 aa
    "TAT_HV1BR_Fernandes_2016",    # 86 aa
    "CCDB_ECOLI_Tripathi_2016",    # 101 aa
    "SUMO1_HUMAN_Weile_2017",      # 101 aa
    "RL401_YEAST_Roscoe_2013",     # 128 aa (ubiquitin)
]


def _cached_download(url: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"  downloading {dest.name}…", flush=True)
        urllib.request.urlretrieve(url, dest)
    return dest


def load_reference() -> dict[str, dict]:
    path = _cached_download(REF_URL, DATA_DIR / "reference.csv")
    ref: dict[str, dict] = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            ref[r["DMS_id"]] = r
    return ref


def load_assay_rows(dms_id: str) -> list[dict]:
    path = _cached_download(ASSAY_URL.format(dms_id=dms_id), DATA_DIR / f"{dms_id}.csv")
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def pick_smallest(ref: dict[str, dict], n: int) -> list[str]:
    singles = [
        (int(r["seq_len"]), did)
        for did, r in ref.items()
        if str(r.get("includes_multiple_mutants", "")).lower() in ("false", "0", "")
        and r.get("seq_len", "").isdigit()
    ]
    return [did for _, did in sorted(singles)[:n]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assays", nargs="*", help="explicit DMS_id list")
    ap.add_argument("--limit", type=int, help="run the N smallest single-mutant assays")
    args = ap.parse_args()

    from benchmark.proteingym import score_assay  # torch-free import
    from worker.scorers.esm2 import ESM2Scorer     # loads torch + the model

    ref = load_reference()
    if args.assays:
        assays = args.assays
    elif args.limit:
        assays = pick_smallest(ref, args.limit)
    else:
        assays = DEFAULT_ASSAYS

    print(f"Loading ESM-2… ({len(assays)} assays to score)")
    scorer = ESM2Scorer()

    results = []
    for dms_id in assays:
        meta = ref.get(dms_id)
        if meta is None:
            print(f"  ! {dms_id} not in reference, skipping")
            continue
        rows = load_assay_rows(dms_id)
        res = score_assay(scorer, dms_id, meta["target_seq"], rows)
        print(
            f"  {dms_id:38} len={meta['seq_len']:>4} "
            f"scored={res.n_scored:>5}/{res.n_mutants:<5} spearman={res.spearman:.3f}"
        )
        results.append(res)

    valid = [r.spearman for r in results if r.spearman == r.spearman]  # drop nan
    mean_rho = sum(valid) / len(valid) if valid else float("nan")
    print(f"\nMean Spearman over {len(valid)} assays: {mean_rho:.3f}")

    out = DATA_DIR / "results.json"
    with open(out, "w") as f:
        json.dump(
            {
                "mean_spearman": mean_rho,
                "assays": [
                    {
                        "dms_id": r.dms_id,
                        "spearman": r.spearman,
                        "scored": [asdict(m) for m in r.scored],
                    }
                    for r in results
                ],
            },
            f,
        )
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
