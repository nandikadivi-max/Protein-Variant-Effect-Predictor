"use client";

import { useState } from "react";
import { Term } from "@/components/Term";
import type { Phase } from "@/lib/usePrediction";

// Each example carries a plain-English "why this one" — without it the chips
// read as a list of accession numbers, which means nothing to a reader who
// doesn't already know the proteins.
const EXAMPLES = [
  {
    label: "TP53 R175H",
    note: "cancer hotspot",
    input: "P04637",
    mutation: "R175H",
  },
  {
    label: "HBB E6V",
    note: "sickle-cell",
    input: "P68871",
    mutation: "E6V",
  },
  {
    label: "SOD1 A4V",
    note: "ALS",
    input: "P00441",
    mutation: "A4V",
  },
  { label: "Insulin", note: "small & fast", input: "P01308", mutation: "" },
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
            Protein{" "}
            <span className="font-normal text-muted/70">
              (a gene name like TP53, a <Term k="uniprot">UniProt ID</Term> like
              P04637, a <Term k="pdb">PDB ID</Term> like 1CRN, or paste a{" "}
              <Term k="fasta">sequence</Term>)
            </span>
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
            Mutation{" "}
            <span className="font-normal text-muted/70">
              (optional, like R175H)
            </span>
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
            className="group rounded-full border border-border px-3 py-1 text-xs text-muted transition-colors hover:border-ink/30 hover:text-ink disabled:opacity-40"
          >
            {ex.label}
            <span className="text-muted/60 group-hover:text-muted">
              {" · "}
              {ex.note}
            </span>
          </button>
        ))}
      </div>
    </form>
  );
}
