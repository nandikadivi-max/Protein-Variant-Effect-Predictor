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


def test_classify_input_rejects_blank():
    """
    Blank input used to fall through to 'name', and a UniProt gene search for
    the empty string is a valid query that returns an arbitrary first hit — so
    an empty form resolved to a real but completely unrelated protein.
    """
    import pytest

    for blank in ("", "   ", "\n", "\t  \n"):
        with pytest.raises(ValueError, match="Enter a protein"):
            classify_input(blank)


def test_classify_input_still_accepts_real_inputs():
    """Guards the blank check against over-reaching."""
    assert classify_input("  P04637  ") == "uniprot_id"
    assert classify_input("tp53") == "name"
    assert classify_input("1CRN") == "pdb_id"


UBQ = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"


def test_classify_input_recognises_fasta_with_a_header():
    """
    Every FASTA file from a database has a '>' header. Testing the raw text
    against the residue alphabet rejected all of them, because '>' and the
    '|' separators are not residues, so real FASTA fell through to gene
    search and came back "no such gene".
    """
    assert classify_input(">sp|P0CG48|UBC_HUMAN Polyubiquitin-C\n" + UBQ) == "fasta"
    assert classify_input(">x\n" + UBQ) == "fasta"
    assert classify_input(UBQ) == "fasta"


def test_classify_input_handles_wrapped_and_windows_line_endings():
    wrapped = "\n".join(UBQ[i : i + 60] for i in range(0, len(UBQ), 60))
    assert classify_input(">x\n" + wrapped) == "fasta"
    assert classify_input(">x\r\n" + wrapped.replace("\n", "\r\n")) == "fasta"


def test_clean_fasta_strips_header_whitespace_and_stops():
    from domain.resolve import clean_fasta

    wrapped = "\n".join(UBQ[i : i + 60] for i in range(0, len(UBQ), 60))
    assert clean_fasta(">sp|X|Y desc\n" + wrapped + "*") == UBQ
    assert clean_fasta(UBQ.lower()) == UBQ
    # Internal spaces (common when copying from a paper) are removed too.
    assert clean_fasta("MQIF VKTL\nTGKT") == "MQIFVKTLTGKT"


def test_short_sequences_are_still_treated_as_gene_names():
    """'MQIFVKTLTG' is a valid peptide but far more likely a gene query, and
    a bare 4-letter run must not be swallowed as a sequence."""
    assert classify_input("MQIFVKTLTG") == "name"
    assert classify_input("TP53") == "name"
