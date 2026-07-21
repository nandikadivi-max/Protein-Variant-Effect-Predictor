import type {
  CreateJobResponse,
  JobStatusResponse,
  ResolveResponse,
  ScoreResult,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
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
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
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

export function structureFileUrl(sequenceHash: string): string {
  return `${API_BASE}/structures/${sequenceHash}/file`;
}
