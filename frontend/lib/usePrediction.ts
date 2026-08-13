"use client";

import { useCallback, useRef, useState } from "react";
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
  // Mirrors state so callbacks with empty dependency lists can read the
  // current result without being recreated on every render.
  const stateRef = useRef(state);
  stateRef.current = state;

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

  /**
   * Look up a different mutation on the protein already on screen.
   *
   * Cheap by construction: the matrix is scored and cached, so this is a
   * single GET that re-derives one number. It never creates a job and never
   * wakes the worker.
   *
   * The result is MERGED, not replaced. `effect_map` and `per_residue_impact`
   * depend only on (sequence_hash, model_id), so they are unchanged — but a
   * fresh response would hand back new array instances, and StructureViewer
   * keys its init effect on `per_residue_impact`. Replacing wholesale would
   * dispose the Mol* plugin, re-download the structure and reset the camera on
   * every click. Preserving identity keeps the viewer untouched.
   */
  const rescoreSeq = useRef(0);
  const [rescoring, setRescoring] = useState(false);

  const rescore = useCallback(async (mutation: string) => {
    const current = stateRef.current.result;
    if (!current) return;

    const seq = ++rescoreSeq.current;
    setRescoring(true);
    try {
      const fresh = await getResult(current.sequence_hash, mutation);
      // A slower earlier click must not overwrite a later one.
      if (seq !== rescoreSeq.current) return;

      setState((prev) =>
        prev.result
          ? {
              ...prev,
              mutation,
              result: {
                ...prev.result,
                single: fresh.single,
                annotation: fresh.annotation,
              },
            }
          : prev,
      );
    } catch {
      // Deliberately swallow: `run`'s catch replaces state wholesale and would
      // drop `result`, unmounting the heatmap, viewer and track over a failed
      // lookup of one cell. Leaving the previous result on screen is better.
      if (seq === rescoreSeq.current) setRescoring(false);
    } finally {
      if (seq === rescoreSeq.current) setRescoring(false);
    }
  }, []);

  const reset = useCallback(() => setState({ phase: "idle" }), []);

  return { ...state, rescoring, run, rescore, reset };
}
