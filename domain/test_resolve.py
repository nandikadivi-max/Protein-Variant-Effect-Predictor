import pytest

from domain.resolve import (
    build_resolved_protein,
    classify_input,
    clean_fasta,
    sequence_hash,
)
from domain.scoring import InvalidResidueError


def test_classify_uniprot_id():
    assert classify_input("P04637") == "uniprot_id"
    assert classify_input("Q9Y6K9") == "uniprot_id"


def test_classify_pdb_id():
    assert classify_input("1TUP") == "pdb_id"


def test_classify_gene_name():
    assert classify_input("TP53") == "name"
    assert classify_input("BRCA1") == "name"


def test_classify_fasta():
    long_seq = "MEEPQSDPSVEPPLSQETFSDLWKLLPENNVLSPLPSQAMDDLMLSPDDIEQWFTEDPGPDEAPRMPEAAPPVAPAPAAPTPAAPAPAPSWPLSSSVPSQK"
    assert classify_input(long_seq) == "fasta"


def test_clean_fasta_strips_header_and_whitespace():
    raw = ">sp|P04637|P53_HUMAN\nMEEPQSD\nPSVEPPLS\n"
    assert clean_fasta(raw) == "MEEPQSDPSVEPPLS"


def test_sequence_hash_is_deterministic():
    a = sequence_hash("MEEPQSD")
    b = sequence_hash("MEEPQSD")
    assert a == b
    assert len(a) == 64  # sha256 hex digest


def test_sequence_hash_dedups_across_input_methods():
    """Same protein via FASTA vs. resolved-from-UniProt must collapse to
    the same cache key — this is the frozen dedup rule."""
    seq_from_fasta = clean_fasta(">header\nMEEPQSD")
    seq_from_uniprot = "MEEPQSD"
    assert sequence_hash(seq_from_fasta) == sequence_hash(seq_from_uniprot)


def test_build_resolved_protein_validates_sequence():
    with pytest.raises(InvalidResidueError):
        build_resolved_protein(
            sequence="MEEPQSDZZZ",
            coordinate_system="fasta",
            uniprot_id=None,
            structure_ref=None,
            source="test",
        )


def test_build_resolved_protein_happy_path():
    protein = build_resolved_protein(
        sequence="MEEPQSD",
        coordinate_system="uniprot",
        uniprot_id="P04637",
        structure_ref=None,
        source="uniprot:P04637",
    )
    assert protein.sequence == "MEEPQSD"
    assert protein.sequence_hash == sequence_hash("MEEPQSD")
