"""
Calibrate the app's damaging / tolerated LLR thresholds against clinical
labels.

The user-facing ESM-2 label is a clinical-relevance call, so we calibrate it
against AlphaMissense (DeepMind's human-clinical-calibrated pathogenicity),
NOT raw DMS fitness — bacterial/yeast growth assays have a different LLR
sensitivity and would mislabel human variants (e.g. TP53 R175H). ProteinGym
(run_benchmark.py) stays as the model-quality benchmark; this sets thresholds.

For each protein we pool every substitution AlphaMissense calls clearly
`pathogenic` or `benign` (ambiguous dropped), pair it with our ESM-2 LLR, and
choose:

  DAMAGING  = highest LLR below which >= TARGET are pathogenic
  TOLERATED = lowest  LLR above which >= TARGET are benign

    python -m benchmark.calibrate [--target 0.85] [--proteins P04637 ...]

Imports torch (ESM-2). Matrices are cached in the normal matrix store, so
re-runs and proteins the app already scored are instant.
"""

import argparse
import urllib.request

import numpy as np

from domain.derive import score_substitution
from domain.resolve import sequence_hash
from domain.scoring import AA_ORDER

# Diverse, clinically-studied human proteins with dense AlphaMissense coverage.
DEFAULT_PROTEINS = [
    "P04637",  # TP53   (393)
    "P60484",  # PTEN   (403)
    "P01116",  # KRAS   (189)
    "P42771",  # CDKN2A (156)
    "P08100",  # RHO    (348)
]
MIN_SUPPORT = 0.05


def fetch_sequence(accession: str) -> str:
    url = f"https://rest.uniprot.org/uniprotkb/{accession}.fasta"
    text = urllib.request.urlopen(url).read().decode()
    return "".join(ln for ln in text.splitlines() if not ln.startswith(">"))


def collect_pairs(proteins: list[str]) -> tuple[np.ndarray, np.ndarray]:
    from api.services.alphamissense_provider import AlphaMissenseProvider
    from storage.matrix_store import get_matrix_store
    from worker.scorers.esm2 import ESM2Scorer

    scorer = ESM2Scorer()
    store = get_matrix_store()
    am = AlphaMissenseProvider()

    llrs: list[float] = []
    labels: list[int] = []  # 1 = pathogenic (damaging), 0 = benign
    for acc in proteins:
        seq = fetch_sequence(acc)
        h = sequence_hash(seq)
        uri = store.build_uri(scorer.model_id, h)
        if store.exists(uri):
            matrix = store.read(uri)
        else:
            matrix = scorer.per_position_log_probs(seq)
            store.write(scorer.model_id, h, matrix)

        n = 0
        for pos in range(1, len(seq) + 1):
            wt = seq[pos - 1]
            for mut in AA_ORDER:
                if mut == wt:
                    continue
                r = am.lookup(acc, f"{wt}{pos}{mut}")
                if r is None:
                    continue
                if r.classification == "pathogenic":
                    labels.append(1)
                elif r.classification == "benign":
                    labels.append(0)
                else:
                    continue
                llrs.append(score_substitution(matrix, pos, wt, mut))
                n += 1
        print(f"  {acc}: {n} labeled substitutions", flush=True)

    order = np.argsort(llrs)
    return np.asarray(llrs)[order], np.asarray(labels)[order]


def damaging_threshold(llr, patho, target, min_n) -> float:
    cum = np.cumsum(patho)
    best = float(llr[0])
    for k in range(min_n, len(llr) + 1):
        if cum[k - 1] / k >= target:
            best = float(llr[k - 1])
    return best


def tolerated_threshold(llr, benign, target, min_n) -> float:
    rev = np.cumsum(benign[::-1])
    best = float(llr[-1])
    for k in range(min_n, len(llr) + 1):
        if rev[k - 1] / k >= target:
            best = float(llr[len(llr) - k])
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=float, default=0.90)
    ap.add_argument("--proteins", nargs="*", default=DEFAULT_PROTEINS)
    args = ap.parse_args()

    print(f"Loading ESM-2 and scoring {len(args.proteins)} proteins…")
    llr, labels = collect_pairs(args.proteins)

    # Balance the classes: AlphaMissense calls a majority of substitutions
    # pathogenic for sensitive proteins (KRAS, PTEN), and that base-rate skew
    # would push the thresholds around. Subsample to 50/50 so the precision
    # targets are symmetric and base-rate-neutral.
    pi = np.where(labels == 1)[0]
    bi = np.where(labels == 0)[0]
    k = min(len(pi), len(bi))
    rng = np.random.default_rng(0)
    keep = np.sort(
        np.concatenate([rng.choice(pi, k, replace=False), rng.choice(bi, k, replace=False)])
    )
    llr, labels = llr[keep], labels[keep]
    reorder = np.argsort(llr)
    llr, labels = llr[reorder], labels[reorder]

    patho = (labels == 1).astype(int)
    benign = (labels == 0).astype(int)
    min_n = max(50, int(MIN_SUPPORT * len(llr)))

    dam_t = damaging_threshold(llr, patho, args.target, min_n)
    tol_t = tolerated_threshold(llr, benign, args.target, min_n)

    print(f"\npooled: {len(llr)} substitutions "
          f"(pathogenic={int(patho.sum())}, benign={int(benign.sum())})")
    print(f"target precision {args.target}, min support {min_n}")
    print(f"\nDAMAGING_LLR_THRESHOLD  = {dam_t:.2f}")
    print(f"TOLERATED_LLR_THRESHOLD = {tol_t:.2f}")

    dmg_tail, tol_tail = llr < dam_t, llr > tol_t
    if dmg_tail.sum():
        print(f"  damaging tail:  {int(dmg_tail.sum()):>6}, "
              f"{patho[dmg_tail].mean():.1%} pathogenic")
    if tol_tail.sum():
        print(f"  tolerated tail: {int(tol_tail.sum()):>6}, "
              f"{benign[tol_tail].mean():.1%} benign")
    band = (~dmg_tail) & (~tol_tail)
    print(f"  uncertain band: {int(band.sum()):>6} ({band.mean():.1%})")


if __name__ == "__main__":
    main()
