"""
Build a compact, queryable SQLite from the AlphaMissense bulk dataset.

The bulk file (AlphaMissense_aa_substitutions.tsv.gz, ~1.2GB gzipped, ~216M
rows) is sorted by uniprot_id. We stream it once and, for each protein, store
a single row: uniprot_id -> gzip-compressed block of "variant\tscore\tclass"
lines. That keeps the DB near the compressed size (~1.2GB) and makes a lookup
a single indexed key fetch + a small in-memory scan, instead of a giant
flat table with a multi-GB index.

Usage:
    python scripts/build_alphamissense_db.py \
        --input data/AlphaMissense_aa_substitutions.tsv.gz \
        --output data/alphamissense.sqlite

Download the input first:
    curl -sL https://storage.googleapis.com/dm_alphamissense/\
AlphaMissense_aa_substitutions.tsv.gz -o data/AlphaMissense_aa_substitutions.tsv.gz
"""

import argparse
import gzip
import sqlite3
import sys
from pathlib import Path


def build(input_path: Path, output_path: Path) -> None:
    if output_path.exists():
        output_path.unlink()  # rebuild from scratch
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("CREATE TABLE am (uniprot_id TEXT PRIMARY KEY, block BLOB)")

    current_id: str | None = None
    buffer: list[str] = []
    proteins = 0
    rows = 0

    def flush() -> None:
        nonlocal proteins
        if current_id is None or not buffer:
            return
        block = gzip.compress("\n".join(buffer).encode("ascii"))
        conn.execute(
            "INSERT OR REPLACE INTO am (uniprot_id, block) VALUES (?, ?)",
            (current_id, block),
        )
        proteins += 1
        if proteins % 2000 == 0:
            conn.commit()
            print(f"  {proteins} proteins, {rows} rows…", flush=True)

    with gzip.open(input_path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            if line.startswith("uniprot_id\t"):
                continue  # header row
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4:
                continue
            uid, variant, score, cls = parts
            if uid != current_id:
                flush()
                current_id = uid
                buffer = []
            # Store only what a lookup needs; uniprot_id is the key.
            buffer.append(f"{variant}\t{score}\t{cls}")
            rows += 1

    flush()
    conn.commit()
    print(f"Done: {proteins} proteins, {rows} rows -> {output_path}", flush=True)
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")
    build(args.input, args.output)


if __name__ == "__main__":
    main()
