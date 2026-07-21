"use client";

import { useState } from "react";
import type { Phase } from "@/lib/usePrediction";

const EXAMPLES = [
  { label: "TP53 R175H", input: "P04637", mutation: "R175H" },
  { label: "Insulin (P01308)", input: "P01308", mutation: "" },
  { label: "Crambin (PDB 1CRN)", input: "1CRN", mutation: "" },
  { label: "BRCA1", input: "BRCA1", mutation: "" },
];

interface Props {
  phase: Phase;
  onSubmit: (input: string, mutation: string) => void;
}

export function PredictionForm({ phase, onSubmit }: Props) {
  const [input, setInput] = useState("");
  const [mutation, setMutation] = useState("");
  const busy = phase !== "idle" && phase !== "done" && phase !== "error";

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (input.trim()) onSubmit(input, mutation);
      }}
      className="space-y-4"
    >
      <div className="grid gap-4 sm:grid-cols-[1fr_auto]">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted">
            Protein — UniProt ID, gene name, PDB ID, or FASTA
          </label>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="P04637"
            spellCheck={false}
            className="w-full rounded-md border border-border bg-surface-raised px-3 py-2 font-mono text-sm outline-none focus:border-ink/30 focus:ring-2 focus:ring-ink/5"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted">
            Mutation <span className="text-muted/60">(optional)</span>
          </label>
          <input
            value={mutation}
            onChange={(e) => setMutation(e.target.value)}
            placeholder="R175H"
            spellCheck={false}
            className="w-full rounded-md border border-border bg-surface-raised px-3 py-2 font-mono text-sm outline-none focus:border-ink/30 focus:ring-2 focus:ring-ink/5 sm:w-36"
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-surface-raised transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? "Working…" : "Predict effect"}
        </button>
        <span className="text-xs text-muted">Try:</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            type="button"
            onClick={() => {
              setInput(ex.input);
              setMutation(ex.mutation);
              onSubmit(ex.input, ex.mutation);
            }}
            disabled={busy}
            className="rounded-full border border-border px-3 py-1 text-xs text-muted transition-colors hover:border-ink/30 hover:text-ink disabled:opacity-40"
          >
            {ex.label}
          </button>
        ))}
      </div>
    </form>
  );
}
