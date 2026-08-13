"""
Per-residue structural features → the StructureContext contract.

Worker-only: this module pulls in pydssp (which depends on torch), so
nothing in api/ may import it. The API only ever *reads* the already-computed
StructureContext that the worker stores.

Why there is no `mkdssp` here any more
--------------------------------------
This originally shelled out to the DSSP binary. That works locally but is
broken in the deployed container: mkdssp 4.x refuses to run without the
wwPDB Chemical Component Dictionary, aborting with a failed assertion in
checkEntities before writing any output. Debian's `dssp` package doesn't
ship the dictionary, `libcifpp-data` only provides the mmCIF dictionary,
and the CCD itself is ~800MB uncompressed. Every protein scored in
production silently came back with no structural features at all.

Secondary structure now comes from pydssp, a pure-Python implementation of
the same hydrogen-bond energy criterion DSSP uses, and solvent accessibility
from Biopython's Shrake-Rupley. No external binary, no dictionary, and the
same code path in development and production.

Coordinate alignment — the whole point of frozen rule #2:
  - AlphaFold models are UniProt-numbered, so residue N maps to UniProt
    position N directly (sifts_segments=None → identity).
  - RCSB experimental structures use author numbering, so we remap each
    residue through the SIFTS segments: unp = author + (unp_start - pdb_start).

The output arrays are always full UniProt length. Residues the structure
doesn't cover (common for experimental crystal structures) keep the
defaults below — meaning "no structural data", not "buried/coil".
"""

import tempfile
import warnings
from pathlib import Path

import numpy as np
from Bio.PDB import PDBParser
from Bio.PDB.SASA import ShrakeRupley

from contracts.schemas import StructureContext

# Below this relative solvent accessibility a residue counts as buried.
BURIED_RSA_THRESHOLD = 0.20

# The four backbone atoms pydssp needs, in the order it expects.
_BACKBONE = ("N", "CA", "C", "O")

# Maximum observed solvent accessibility per residue type (Å²), used to turn
# absolute Shrake-Rupley SASA into a 0-1 relative value. Theoretical values
# from Tien et al. 2013, the same reference DSSP-derived RSA conventionally
# uses, so the numbers stay comparable to the previously stored features.
_MAX_ASA = {
    "ALA": 129.0, "ARG": 274.0, "ASN": 195.0, "ASP": 193.0, "CYS": 167.0,
    "GLU": 223.0, "GLN": 225.0, "GLY": 104.0, "HIS": 224.0, "ILE": 197.0,
    "LEU": 201.0, "LYS": 236.0, "MET": 224.0, "PHE": 240.0, "PRO": 159.0,
    "SER": 155.0, "THR": 172.0, "TRP": 285.0, "TYR": 263.0, "VAL": 174.0,
}


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
    Assign per-residue secondary structure and relative solvent accessibility,
    projected onto UniProt coordinates.
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
            ShrakeRupley().compute(model, level="R")

    # Collect residues with a complete backbone, keeping their identity so the
    # per-index assignment below can be mapped back to UniProt positions.
    residues: list[tuple[str, int, str, float]] = []  # chain, resnum, name, sasa
    coords: list[list[list[float]]] = []
    for chain in model:
        for res in chain:
            if res.id[0] != " ":
                continue  # hetero/water
            if not all(atom in res for atom in _BACKBONE):
                continue  # incomplete backbone; pydssp needs all four
            coords.append([list(res[atom].get_coord()) for atom in _BACKBONE])
            residues.append(
                (chain.id, res.id[1], res.get_resname().upper(), float(res.sasa))
            )

    if not residues:
        return StructureContext(
            secondary_structure=secondary,
            relative_sasa=rel_sasa,
            buried=buried,
        )

    # One assignment over every chain at once, so inter-chain sheets are seen.
    import pydssp

    ss3 = pydssp.assign(np.asarray(coords, dtype=np.float32), out_type="c3")

    for (chain_id, author_resnum, resname, sasa), ss in zip(residues, ss3):
        unp_pos = _map_to_uniprot(chain_id, author_resnum, sifts_segments)
        if unp_pos is None or not (1 <= unp_pos <= seq_length):
            continue

        rsa = sasa / _MAX_ASA.get(resname, 200.0)
        rsa = max(0.0, min(1.0, rsa))

        i = unp_pos - 1
        # pydssp emits '-' for coil; the contract uses 'C'.
        secondary[i] = ss if ss in ("H", "E") else "C"
        rel_sasa[i] = rsa
        buried[i] = rsa < BURIED_RSA_THRESHOLD

    return StructureContext(
        secondary_structure=secondary,
        relative_sasa=rel_sasa,
        buried=buried,
    )
