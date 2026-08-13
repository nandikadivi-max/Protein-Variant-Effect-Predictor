"""
SIFTS segments must survive PDBe's occasional missing author residue number.

1TUP — the canonical p53 structure, and the one this project demos — comes
back with a null author number at the end of its mapping. Stored as-is, that
null raised inside the range comparison every consumer performs, and because
feature computation is best-effort it looked like the structure simply had
no features.
"""

from api.services.sifts_client import _segment_from_mapping


def mapping(start, end, unp_start, unp_end, chain="A") -> dict:
    return {
        "chain_id": chain,
        "start": {"author_residue_number": start},
        "end": {"author_residue_number": end},
        "unp_start": unp_start,
        "unp_end": unp_end,
    }


def test_missing_author_end_is_reconstructed_from_the_span():
    """The real 1TUP shape: p53 DBD, author start 94, UniProt 94-312."""
    seg = _segment_from_mapping(mapping(94, None, 94, 312))
    assert seg is not None
    assert seg.pdb_start == 94
    assert seg.pdb_end == 312          # 94 + (312 - 94)
    assert seg.unp_start == 94


def test_reconstruction_respects_a_real_offset():
    """Author numbering need not equal UniProt numbering."""
    seg = _segment_from_mapping(mapping(1, None, 94, 312))
    assert seg is not None
    assert seg.pdb_end == 219          # 1 + 218 residues
    # The offset a consumer applies must place the last residue at 312.
    assert seg.pdb_end + (seg.unp_start - seg.pdb_start) == 312


def test_intact_mappings_are_untouched():
    seg = _segment_from_mapping(mapping(94, 312, 94, 312))
    assert seg is not None and (seg.pdb_start, seg.pdb_end) == (94, 312)


def test_unusable_mappings_are_dropped_not_guessed():
    """A missing start cannot be reconstructed, so the segment is discarded
    rather than silently mis-mapping every residue in it."""
    assert _segment_from_mapping(mapping(None, 312, 94, 312)) is None
    assert _segment_from_mapping(mapping(94, 312, None, 312)) is None
    assert _segment_from_mapping(mapping(94, 312, 94, None)) is None


def test_sibling_chains_inherit_a_known_offset():
    """
    1TUP is a p53 trimer: PDBe maps chains A, B and C to UniProt 94-312, but
    reports an author residue number only for chain A. Dropping the other two
    leaves a structure where one chain is coloured and two identical copies
    are blank, which reads as a bug.
    """
    from api.services.sifts_client import _segments_from_mappings

    segs = _segments_from_mappings([
        mapping(94, None, 94, 312, chain="A"),
        mapping(None, None, 94, 312, chain="B"),
        mapping(None, None, 94, 312, chain="C"),
    ])
    assert {s.chain_id for s in segs} == {"A", "B", "C"}
    for s in segs:
        assert (s.pdb_start, s.pdb_end) == (94, 312)
        assert s.unp_start - s.pdb_start == 0


def test_sibling_reconstruction_carries_a_real_offset():
    """When the known chain is offset, the inferred ones must match it."""
    from api.services.sifts_client import _segments_from_mappings

    segs = _segments_from_mappings([
        mapping(1, None, 94, 312, chain="A"),     # offset +93
        mapping(None, None, 94, 312, chain="B"),
    ])
    by_chain = {s.chain_id: s for s in segs}
    assert by_chain["B"].pdb_start == 1 and by_chain["B"].pdb_end == 219
    assert by_chain["B"].unp_start - by_chain["B"].pdb_start == 93


def test_nothing_is_invented_when_no_chain_is_numbered():
    """With no anchor at all, guessing would mis-map every residue."""
    from api.services.sifts_client import _segments_from_mappings

    assert _segments_from_mappings([
        mapping(None, None, 94, 312, chain="A"),
        mapping(None, None, 94, 312, chain="B"),
    ]) == ()
