"""
DSSP-derived structural features → the StructureContext contract.

Worker-only: this module shells out to the `dssp`/`mkdssp` binary (present
in the worker image, never the thin API image), so nothing in api/ may
import it. The API only ever *reads* the already-computed StructureContext
that the worker stores.

Coordinate alignment — the whole point of frozen rule #2:
  - AlphaFold models are UniProt-numbered, so residue N maps to UniProt
    position N directly (sifts_segments=None → identity).
  - RCSB experimental structures use author numbering, so we remap each
    residue through the SIFTS segments: unp = author + (unp_start - pdb_start).

The output arrays are always full UniProt length. Residues the structure
doesn't cover (common for experimental crystal structures) keep the
defaults below — meaning "no structural data", not "buried/coil".
"""

import shutil
import tempfile
import warnings
from pathlib import Path

from Bio.PDB import DSSP, PDBParser

from contracts.schemas import StructureContext

# Below this relative solvent accessibility a residue counts as buried.
BURIED_RSA_THRESHOLD = 0.20

# DSSP 8-state → 3-state (helix / strand / coil).
_SS3 = {"H": "H", "G": "H", "I": "H", "E": "E", "B": "E"}


def _dssp_executable() -> str:
    for name in ("mkdssp", "dssp"):
        if shutil.which(name):
            return name
    raise RuntimeError("No dssp/mkdssp binary found on PATH")


def _map_to_uniprot(
    chain_id: str, author_resnum: int, sifts_segments: list[dict] | None
) -> int | None:
    """Return the 1-based UniProt position for a structure residue, or None."""
    if sifts_segments is None:
        # AlphaFold: chain residue numbering already IS UniProt numbering.
        return author_resnum
    for seg in sifts_segments:
        if seg["chain_id"] != chain_id:
            continue
        if seg["pdb_start"] <= author_resnum <= seg["pdb_end"]:
            return author_resnum + (seg["unp_start"] - seg["pdb_start"])
    return None


def compute_structure_context(
    pdb_bytes: bytes,
    seq_length: int,
    sifts_segments: list[dict] | None = None,
) -> StructureContext:
    """
    Run DSSP over a structure file and project per-residue secondary
    structure + relative solvent accessibility onto UniProt coordinates.
    """
    secondary = ["C"] * seq_length
    rel_sasa = [0.0] * seq_length
    buried = [False] * seq_length

    with tempfile.NamedTemporaryFile(suffix=".pdb", delete=True) as tmp:
        tmp.write(pdb_bytes)
        tmp.flush()
        path = Path(tmp.name)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # PDBConstructionWarning noise
            model = PDBParser(QUIET=True).get_structure("s", str(path))[0]
            dssp = DSSP(model, str(path), dssp=_dssp_executable())

        for key in dssp.keys():
            chain_id = key[0]
            author_resnum = key[1][1]  # (hetflag, resseq, icode)
            unp_pos = _map_to_uniprot(chain_id, author_resnum, sifts_segments)
            if unp_pos is None or not (1 <= unp_pos <= seq_length):
                continue

            record = dssp[key]
            ss8 = record[2]
            try:
                rsa = float(record[3])
            except (TypeError, ValueError):
                continue  # DSSP reports 'NA' for residues it can't score
            rsa = max(0.0, min(1.0, rsa))

            i = unp_pos - 1
            secondary[i] = _SS3.get(ss8, "C")
            rel_sasa[i] = rsa
            buried[i] = rsa < BURIED_RSA_THRESHOLD

    return StructureContext(
        secondary_structure=secondary,
        relative_sasa=rel_sasa,
        buried=buried,
    )
