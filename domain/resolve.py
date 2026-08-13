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

# Letters that may appear in a pasted sequence body. X (unknown residue) and
# * (stop) are tolerated at classification time so the paste is recognised as
# a sequence; validate_sequence is what actually rejects non-canonical
# residues, with a message that names them.
FASTA_ALPHABET = "ACDEFGHIKLMNPQRSTVWYX*"


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
    """
    Return one of: 'uniprot_id', 'pdb_id', 'fasta', 'name'.

    Blank input is rejected rather than falling through to 'name'. A gene
    search for the empty string is a valid query upstream and comes back with
    an arbitrary first hit, so an empty form would resolve to a real but
    entirely unrelated protein.
    """
    stripped = raw_input.strip()
    if not stripped:
        raise ValueError("Enter a protein: a gene name, UniProt ID, PDB ID, or sequence.")
    if UNIPROT_PATTERN.match(stripped.upper()):
        return "uniprot_id"
    if PDB_ID_PATTERN.match(stripped) and any(c.isdigit() for c in stripped[:1]):
        return "pdb_id"

    # A '>' header is unambiguous FASTA, and it is what you get from every
    # database download. Testing the raw text against the residue alphabet
    # missed all of those, because '>' and the '|' separators in the header
    # aren't residues — so a real FASTA file fell through to gene search and
    # came back "no such gene". Classify on the sequence body instead, which
    # also lets a genuinely malformed paste fail with a residue error rather
    # than a misleading lookup failure.
    if stripped.startswith(">"):
        return "fasta"
    body = _sequence_body(stripped)
    if len(body) > 20 and set(body) <= set(FASTA_ALPHABET):
        return "fasta"
    return "name"


def _sequence_body(raw: str) -> str:
    """
    The residue letters of a pasted block: header lines dropped, all
    whitespace removed, uppercased. Shared by classification and cleaning so
    the two can never disagree about what counts as the sequence.
    """
    lines = [ln for ln in raw.strip().splitlines() if not ln.lstrip().startswith(">")]
    return "".join("".join(ln.split()) for ln in lines).upper()


def clean_fasta(raw: str) -> str:
    """Strip '>' header lines, whitespace and stop codons from a pasted block."""
    return _sequence_body(raw).replace("*", "")


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
