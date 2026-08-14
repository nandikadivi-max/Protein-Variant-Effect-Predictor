import type {
  CreateJobResponse,
  JobStatusResponse,
  ResolveResponse,
  ScoreResult,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1";

/** A "did you mean" candidate the API offers alongside a rejection. */
export interface ProteinSuggestion {
  input: string;
  label: string;
  reason: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** Alternatives the API computed; empty when it had nothing defensible. */
    public suggestions: ProteinSuggestion[] = [],
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let message = res.statusText;
    let suggestions: ProteinSuggestion[] = [];
    try {
      const { detail } = await res.json();
      // FastAPI's detail is a plain string for simple errors, and an object
      // when the API has corrections to offer. Accept both so older responses
      // and validation errors still surface something readable.
      if (typeof detail === "string") {
        message = detail;
      } else if (detail && typeof detail === "object") {
        message = detail.message ?? message;
        suggestions = detail.suggestions ?? [];
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message, suggestions);
  }
  return res.json() as Promise<T>;
}

export function resolveProtein(
  input: string,
  mutation?: string,
): Promise<ResolveResponse> {
  return request("/proteins/resolve", {
    method: "POST",
    body: JSON.stringify({ input, mutation: mutation || null }),
  });
}

export function createJob(sequenceHash: string): Promise<CreateJobResponse> {
  return request("/jobs", {
    method: "POST",
    body: JSON.stringify({ sequence_hash: sequenceHash }),
  });
}

export function getJob(jobId: string): Promise<JobStatusResponse> {
  return request(`/jobs/${jobId}`);
}

export function getResult(
  sequenceHash: string,
  mutation?: string,
): Promise<ScoreResult> {
  const q = mutation ? `?mutation=${encodeURIComponent(mutation)}` : "";
  return request(`/results/${sequenceHash}${q}`);
}

export interface CachedProtein {
  uniprot_id: string;
  gene: string;
  name: string;
  length: number;
  sequence_hash: string;
}

/** Proteins already scored, and so instant to open. */
export function getCachedProteins(limit = 12): Promise<CachedProtein[]> {
  return request(`/proteins/cached?limit=${limit}`);
}

export interface SiftsSegment {
  chain_id: string;
  pdb_start: number;
  pdb_end: number;
  unp_start: number;
  unp_end: number;
}

export interface StructureInfo {
  sequence_hash: string;
  provider: string;
  format: string;
  source_url: string;
  file_url: string;
  sifts_segments: SiftsSegment[];
}

/** Structure metadata, including the numbering map the viewer colours by. */
export function getStructureInfo(
  sequenceHash: string,
  provider?: string | null,
): Promise<StructureInfo> {
  const q = provider ? `?provider=${encodeURIComponent(provider)}` : "";
  return request(`/structures/${sequenceHash}${q}`);
}

export function structureFileUrl(
  sequenceHash: string,
  provider?: string | null,
): string {
  const q = provider ? `?provider=${encodeURIComponent(provider)}` : "";
  return `${API_BASE}/structures/${sequenceHash}/file${q}`;
}
