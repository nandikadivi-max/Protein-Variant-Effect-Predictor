"use client";

import { useEffect, useState } from "react";
import { Term } from "@/components/Term";
import { getCachedProteins, type CachedProtein } from "@/lib/api";
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
  // Positions are UniProt canonical, which counts the initiator methionine.
  // The familiar clinical names for these two (HBB E6V, SOD1 A4V) number the
  // MATURE protein, after that methionine is cleaved, so both are one lower
  // than the value this app needs. Using the clinical numbering here returns
  // a reference mismatch, because position 6 of HBB is proline and position
  // 4 of SOD1 is lysine.
  {
    label: "HBB E7V",
    note: "sickle-cell",
    input: "P68871",
    mutation: "E7V",
  },
  {
    label: "SOD1 A5V",
    note: "ALS",
    input: "P00441",
    mutation: "A5V",
  },
  { label: "Insulin", note: "small & fast", input: "P01308", mutation: "" },
];

interface Props {
  phase: Phase;
  onSubmit: (input: string, mutation: string) => void;
  // Controlled from the page rather than held here, so a prediction started
  // from a shared URL can fill these boxes. Keeping the state local left both
  // fields blank while such a run was in flight, and a lazy useState
  // initialiser reading the URL would differ between server and client render.
  input: string;
  mutation: string;
  onInputChange: (value: string) => void;
  onMutationChange: (value: string) => void;
}

export function PredictionForm({
  phase,
  onSubmit,
  input,
  mutation,
  onInputChange,
  onMutationChange,
}: Props) {
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
            onChange={(e) => onInputChange(e.target.value)}
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
            onChange={(e) => onMutationChange(e.target.value)}
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
              onInputChange(ex.input);
              onMutationChange(ex.mutation);
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

      <AlreadyScored
        busy={busy}
        exclude={EXAMPLES.map((e) => e.input)}
        onPick={(accession) => {
          onInputChange(accession);
          onMutationChange("");
          onSubmit(accession, "");
        }}
      />
    </form>
  );
}

/**
 * Proteins somebody has already scored, which therefore return instantly.
 *
 * The cache grows on its own with use, so this row fills out over time rather
 * than staying whatever was seeded at launch. Rendered only when there is
 * something to show beyond the examples above, and silently absent if the
 * lookup fails — it is a convenience, not part of the flow.
 */
function AlreadyScored({
  busy,
  exclude,
  onPick,
}: {
  busy: boolean;
  exclude: string[];
  onPick: (accession: string) => void;
}) {
  const [items, setItems] = useState<CachedProtein[]>([]);

  useEffect(() => {
    let cancelled = false;
    getCachedProteins(16)
      .then((all) => {
        if (cancelled) return;
        const skip = new Set(exclude);
        setItems(all.filter((p) => !skip.has(p.uniprot_id)).slice(0, 8));
      })
      .catch(() => {
        /* nothing to show; the examples above still work */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
      <span className="text-xs text-muted">
        Already scored, so instant:
      </span>
      {items.map((p) => (
        <button
          key={p.uniprot_id}
          type="button"
          onClick={() => onPick(p.uniprot_id)}
          disabled={busy}
          title={p.name || p.uniprot_id}
          className="group rounded-full border border-border px-3 py-1 text-xs text-muted transition-colors hover:border-ink/30 hover:text-ink disabled:opacity-40"
        >
          {p.gene}
          <span className="text-muted/60 group-hover:text-muted">
            {" · "}
            {p.length} aa
          </span>
        </button>
      ))}
    </div>
  );
}
