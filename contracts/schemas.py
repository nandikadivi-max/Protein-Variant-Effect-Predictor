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


class CachedProtein(BaseModel):
    """A protein already scored, and therefore instant to open."""

    uniprot_id: str
    gene: str
    name: str
    length: int
    sequence_hash: str


class MutationSuggestion(BaseModel):
    """A correction the client can apply directly, with its justification."""

    mutation: str = Field(..., description="The corrected mutation, e.g. 'E7V'")
    reason: str = Field(..., description="Why this is being suggested")


class ResolveResponse(BaseModel):
    sequence_hash: str
    length: int
    uniprot_id: str | None
    coordinate_system: str
    source: str
    has_structure: bool
    mutation_valid: bool | None = None
    mutation_error: str | None = None
    # Populated only when mutation_valid is False: a plain-language account of
    # what is wrong, plus corrections the client can offer as one-click fixes.
    mutation_explanation: str | None = None
    mutation_suggestions: list[MutationSuggestion] = Field(default_factory=list)


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


class SiftsSegment(BaseModel):
    """One contiguous author-numbering -> UniProt-numbering run in a chain."""

    chain_id: str
    pdb_start: int
    pdb_end: int
    unp_start: int
    unp_end: int


class StructureInfo(BaseModel):
    """Metadata for a fetched 3D structure file (served to the Mol* viewer)."""
    sequence_hash: str
    provider: str        # "alphafold" | "rcsb"
    format: str          # "pdb"
    source_url: str      # upstream provenance (AlphaFold DB / RCSB)
    file_url: str        # our endpoint that streams the raw bytes
    # Empty for AlphaFold, whose residue numbering already IS UniProt
    # numbering. For an experimental entry these are what let the viewer
    # colour by UniProt position instead of by the file's own numbering —
    # without them a cropped structure is coloured with a constant offset.
    sifts_segments: list[SiftsSegment] = Field(default_factory=list)


class StructureContext(BaseModel):
    secondary_structure: list[str]  # per-residue, "H" | "E" | "C"
    relative_sasa: list[float]      # per-residue, 0-1
    buried: list[bool]              # per-residue, RSA < 0.20


class Confidence(BaseModel):
    """[EXT] populated once >=2 scorers exist (inter-model agreement)."""
    score: float
    method: str


class VariantPrediction(BaseModel):
    """A third-party predictor's call for a variant (SIFT, PolyPhen, ...)."""
    algorithm: str                 # "SIFT" | "PolyPhen" | (future) "AlphaMissense"
    prediction: str | None = None  # e.g. "deleterious" | "benign"
    score: float | None = None


class VariantAnnotation(BaseModel):
    """
    External knowledge about a specific mutation, sourced from the EBI
    Proteins variation API (ClinVar/Ensembl/UniProt/NCI-TCGA). Distinct from
    our own ESM-2 score in `single` — this is what other databases *say*.
    """
    mutation: str
    clinical_significance: str | None = None   # "Pathogenic" | "Benign" | "Uncertain" | ...
    sources: list[str] = []                    # ["ClinVar", "Ensembl", ...]
    diseases: list[str] = []                   # associated disease/trait names
    predictions: list[VariantPrediction] = []


class ScoreResult(BaseModel):
    sequence_hash: str
    model_id: str
    length: int
    single: SingleScore | None = None
    effect_map: list[list[float]]       # L x 20, columns in AA_ORDER
    per_residue_impact: list[float]     # L
    structure: StructureContext | None = None
    annotation: VariantAnnotation | None = None
    confidence: Confidence | None = None
