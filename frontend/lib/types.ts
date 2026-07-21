// Mirrors contracts/schemas.py. Keep in sync with the frozen API contract.

export const AA_ORDER = "ACDEFGHIKLMNPQRSTVWY".split("");

export type JobStatus = "queued" | "running" | "done" | "error";
export type EffectLabel = "likely_damaging" | "uncertain" | "likely_tolerated";

export interface ResolveResponse {
  sequence_hash: string;
  length: number;
  uniprot_id: string | null;
  coordinate_system: string;
  source: string;
  has_structure: boolean;
  mutation_valid: boolean | null;
  mutation_error: string | null;
}

export interface CreateJobResponse {
  job_id: string;
  status: JobStatus;
  cached: boolean;
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  error: string | null;
}

export interface SingleScore {
  mutation: string;
  llr: number;
  percentile: number | null;
  label: EffectLabel;
}

export interface StructureContext {
  secondary_structure: string[]; // "H" | "E" | "C"
  relative_sasa: number[];
  buried: boolean[];
}

export interface VariantPrediction {
  algorithm: string;
  prediction: string | null;
  score: number | null;
}

export interface VariantAnnotation {
  mutation: string;
  clinical_significance: string | null;
  sources: string[];
  diseases: string[];
  predictions: VariantPrediction[];
}

export interface ScoreResult {
  sequence_hash: string;
  model_id: string;
  length: number;
  single: SingleScore | null;
  effect_map: number[][]; // L x 20, columns in AA_ORDER
  per_residue_impact: number[]; // L
  structure: StructureContext | null;
  annotation: VariantAnnotation | null;
}
