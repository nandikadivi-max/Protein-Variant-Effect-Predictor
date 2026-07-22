# Benchmark & calibration

Two separate offline harnesses, run from the repo root with the `.[worker]`
env active (they import the ESM-2 scorer). Downloaded data is cached under
`data/proteingym/` and `data/matrices/` (both gitignored).

## 1. ProteinGym benchmark — *validates the model*

Measures how well the zero-shot ESM-2 LLR tracks experimental fitness across
[ProteinGym](https://proteingym.org) deep-mutational-scanning assays
(Spearman rank correlation — the field-standard metric).

```bash
python -m benchmark.run_benchmark            # curated 5-assay set
python -m benchmark.run_benchmark --limit 10 # 10 smallest single-mutant assays
```

Result on the curated set (ESM-2 650M, masked-marginal):

| Assay | len | Spearman |
|---|---|---|
| IF1_ECOLI_Kelsic_2016 | 72 | 0.599 |
| TAT_HV1BR_Fernandes_2016 | 86 | 0.017 |
| CCDB_ECOLI_Tripathi_2016 | 101 | 0.511 |
| SUMO1_HUMAN_Weile_2017 | 101 | 0.509 |
| RL401_YEAST_Roscoe_2013 | 128 | 0.599 |
| **mean** | | **0.447** |

In line with published ESM-2 650M ProteinGym numbers (~0.41–0.44). TAT is a
viral protein, a known weak spot for protein LMs.

## 2. Threshold calibration — *sets the user-facing label*

The app's `likely_damaging / uncertain / likely_tolerated` label is a
clinical-relevance call, so it's calibrated against **AlphaMissense**
(DeepMind's human-clinical-calibrated pathogenicity), not raw DMS fitness —
bacterial/yeast growth assays have a different LLR sensitivity and would
mislabel human variants (e.g. TP53 R175H).

```bash
python -m benchmark.calibrate                # 5 human proteins, 90% precision
```

Pooling ~15k class-balanced pathogenic/benign substitutions across TP53,
PTEN, KRAS, CDKN2A and RHO, at a 90% precision target:

- `DAMAGING_LLR_THRESHOLD  = -5.50`  (LLR below → 90% pathogenic)
- `TOLERATED_LLR_THRESHOLD = -1.33`  (LLR above → 90% benign)
- ~31% of substitutions fall in the honest "uncertain" band between.

These land in `api/services/results_service.py`.
