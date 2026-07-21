"""
Input resolution: turn a UniProt ID, PDB ID, gene name, or raw FASTA into a
ResolvedProtein with a canonical sequence and a stable cache key.

FROZEN RULE: the cache key is sha256(sequence), not any external ID. The
same residues arriving via different input methods must collapse to the
same cached matrix.
"""

import hashlib
import re
from dataclasses import dataclass

from domain.scoring import validate_sequence

UNIPROT_PATTERN = re.compile(
    r"^[OPQ][0-9][A-Z0-9]{3}[0-9]$|^[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}$"
)
PDB_ID_PATTERN = re.compile(r"^[0-9][A-Za-z0-9]{3}$")


@dataclass(frozen=True)
class StructureRef:
    provider: str  # "alphafold" | "rcsb"
    identifier: str  # uniprot accession for alphafold, pdb id for rcsb


@dataclass(frozen=True)
class ResolvedProtein:
    sequence: str
    sequence_hash: str
    coordinate_system: str  # "uniprot" | "fasta"
    uniprot_id: str | None
    structure_ref: StructureRef | None
    source: str  # human-readable provenance for the UI


def sequence_hash(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def classify_input(raw_input: str) -> str:
    """Return one of: 'uniprot_id', 'pdb_id', 'fasta', 'name'."""
    stripped = raw_input.strip()
    if UNIPROT_PATTERN.match(stripped.upper()):
        return "uniprot_id"
    if PDB_ID_PATTERN.match(stripped) and any(c.isdigit() for c in stripped[:1]):
        return "pdb_id"
    if len(stripped) > 20 and set(stripped.upper()) <= set("ACDEFGHIKLMNPQRSTVWYX*\n "):
        return "fasta"
    return "name"


def clean_fasta(raw: str) -> str:
    """Strip a '>' header line and whitespace from a pasted FASTA block."""
    lines = [line for line in raw.strip().splitlines() if not line.startswith(">")]
    return "".join(lines).strip().upper().replace("*", "")


def build_resolved_protein(
    sequence: str,
    coordinate_system: str,
    uniprot_id: str | None,
    structure_ref: StructureRef | None,
    source: str,
) -> ResolvedProtein:
    """Central constructor — validates the sequence before anything is cached."""
    validate_sequence(sequence)
    return ResolvedProtein(
        sequence=sequence,
        sequence_hash=sequence_hash(sequence),
        coordinate_system=coordinate_system,
        uniprot_id=uniprot_id,
        structure_ref=structure_ref,
        source=source,
    )

# NOTE: the actual network calls (UniProt REST, RCSB, AlphaFold DB) live in
# api/services/uniprot_client.py etc. This module stays pure/testable and
# only defines the shape and the validation rules those clients must satisfy.
