"use client";

import { useCallback, useState } from "react";
import { createJob, getJob, getResult, resolveProtein } from "./api";
import type { ResolveResponse, ScoreResult } from "./types";

export type Phase =
  | "idle"
  | "resolving"
  | "queued"
  | "running"
  | "done"
  | "error";

export interface PredictionState {
  phase: Phase;
  resolved?: ResolveResponse;
  result?: ScoreResult;
  mutation?: string;
  error?: string;
  /** False when this protein had to be scored from scratch. Lets the UI warn
   *  that the wait is minutes rather than leaving a bare spinner. */
  cached?: boolean;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function usePrediction() {
  const [state, setState] = useState<PredictionState>({ phase: "idle" });

  const run = useCallback(async (input: string, mutation?: string) => {
    const mut = mutation?.trim() || undefined;
    try {
      setState({ phase: "resolving", mutation: mut });

      const resolved = await resolveProtein(input.trim(), mut);
      // A bad mutation shouldn't block scoring the protein — surface it but
      // continue; the heatmap and per-residue view are still useful.
      const usableMutation =
        mut && resolved.mutation_valid === false ? undefined : mut;

      setState({ phase: "queued", resolved, mutation: mut });

      const job = await createJob(resolved.sequence_hash);
      const cached = job.cached;
      let status = job.status;
      while (status === "queued" || status === "running") {
        setState({ phase: status, resolved, mutation: mut, cached });
        await sleep(1200);
        const js = await getJob(job.job_id);
        status = js.status;
        if (status === "error") {
          throw new Error(js.error ?? "Scoring failed in the worker.");
        }
      }

      const result = await getResult(resolved.sequence_hash, usableMutation);
      setState({ phase: "done", resolved, result, mutation: mut, cached });
    } catch (e) {
      setState({ phase: "error", error: (e as Error).message, mutation: mut });
    }
  }, []);

  const reset = useCallback(() => setState({ phase: "idle" }), []);

  return { ...state, run, reset };
}
