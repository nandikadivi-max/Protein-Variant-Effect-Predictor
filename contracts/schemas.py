"""
Frozen Pydantic schemas — the contract between frontend, api, and worker.
No torch, no model imports here. Changing these later means a frontend
change too, so get the shape right before building on top of it.
"""

from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class EffectLabel(str, Enum):
    LIKELY_DAMAGING = "likely_damaging"
    UNCERTAIN = "uncertain"
    LIKELY_TOLERATED = "likely_tolerated"


class ResolveRequest(BaseModel):
    input: str = Field(..., description="UniProt ID, PDB ID, gene name, or raw FASTA")
    mutation: str | None = Field(None, description="e.g. 'R248Q' or 'R248Q:D281N'")


class ResolveResponse(BaseModel):
    sequence_hash: str
    length: int
    uniprot_id: str | None
    coordinate_system: str
    source: str
    has_structure: bool
    mutation_valid: bool | None = None
    mutation_error: str | None = None


class CreateJobRequest(BaseModel):
    sequence_hash: str
    model_id: str = "esm2_t33_650M_UR50D"


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    cached: bool


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    error: str | None = None


class SingleScore(BaseModel):
    mutation: str
    llr: float
    percentile: float | None = None
    label: EffectLabel


class StructureInfo(BaseModel):
    """Metadata for a fetched 3D structure file (served to the Mol* viewer)."""
    sequence_hash: str
    provider: str        # "alphafold" | "rcsb"
    format: str          # "pdb"
    source_url: str      # upstream provenance (AlphaFold DB / RCSB)
    file_url: str        # our endpoint that streams the raw bytes


class StructureContext(BaseModel):
    secondary_structure: list[str]  # per-residue, "H" | "E" | "C"
    relative_sasa: list[float]      # per-residue, 0-1
    buried: list[bool]              # per-residue, RSA < 0.20


class Confidence(BaseModel):
    """[EXT] populated once >=2 scorers exist (inter-model agreement)."""
    score: float
    method: str


class ScoreResult(BaseModel):
    sequence_hash: str
    model_id: str
    length: int
    single: SingleScore | None = None
    effect_map: list[list[float]]       # L x 20, columns in AA_ORDER
    per_residue_impact: list[float]     # L
    structure: StructureContext | None = None
    confidence: Confidence | None = None
