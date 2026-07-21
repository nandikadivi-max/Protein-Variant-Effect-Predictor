"use client";

import dynamic from "next/dynamic";
import { EffectHeatmap } from "@/components/EffectHeatmap";
import { PredictionForm } from "@/components/PredictionForm";
import { SingleScoreCard } from "@/components/SingleScoreCard";
import { structureFileUrl } from "@/lib/api";
import { usePrediction } from "@/lib/usePrediction";

// Mol* is client-only (WebGL, no SSR).
const StructureViewer = dynamic(
  () => import("@/components/StructureViewer").then((m) => m.StructureViewer),
  { ssr: false },
);

const PHASE_TEXT: Record<string, string> = {
  resolving: "Resolving protein…",
  queued: "Queued for scoring…",
  running: "Scoring with ESM-2 (first time per protein is slower)…",
};

export default function Home() {
  const p = usePrediction();

  const single = p.result?.single ?? null;
  const highlight = single ? parseMutation(single.mutation) : null;
  const busy = ["resolving", "queued", "running"].includes(p.phase);

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">
          Protein Variant Effect Predictor
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Zero-shot missense variant scoring with ESM-2. Enter a protein and an
          optional mutation to see a full effect map, the specific substitution
          score, and any known clinical annotation.
        </p>
      </header>

      <section className="rounded-lg border border-border bg-surface-raised p-5">
        <PredictionForm phase={p.phase} onSubmit={p.run} />
      </section>

      {busy && (
        <div className="mt-6 flex items-center gap-3 text-sm text-muted">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-border border-t-ink" />
          {PHASE_TEXT[p.phase]}
        </div>
      )}

      {p.phase === "error" && (
        <div className="mt-6 rounded-md border border-damaging/30 bg-damaging/5 px-4 py-3 text-sm text-damaging">
          {p.error}
        </div>
      )}

      {p.resolved && p.mutation && p.resolved.mutation_valid === false && (
        <div className="mt-6 rounded-md border border-border bg-surface-raised px-4 py-3 text-sm text-muted">
          Mutation <span className="font-mono">{p.mutation}</span> doesn&apos;t
          match this sequence ({p.resolved.mutation_error}). Showing the full
          effect map instead.
        </div>
      )}

      {p.result && (
        <div className="mt-8 space-y-6">
          <ResolvedMeta result={p.result} source={p.resolved?.source} />
          {single && (
            <SingleScoreCard single={single} annotation={p.result.annotation} />
          )}
          {p.resolved?.has_structure && (
            <StructureViewer
              fileUrl={structureFileUrl(p.result.sequence_hash)}
              perResidueImpact={p.result.per_residue_impact}
            />
          )}
          <EffectHeatmap effectMap={p.result.effect_map} highlight={highlight} />
        </div>
      )}
    </main>
  );
}

function ResolvedMeta({
  result,
  source,
}: {
  result: NonNullable<ReturnType<typeof usePrediction>["result"]>;
  source?: string;
}) {
  const items: [string, string][] = [
    ["Length", `${result.length} aa`],
    ["Model", result.model_id],
  ];
  if (source) items.unshift(["Source", source]);
  if (result.structure) items.push(["Structure", "available"]);
  return (
    <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
      {items.map(([k, v]) => (
        <div key={k}>
          <span className="text-muted">{k}: </span>
          <span className="font-mono">{v}</span>
        </div>
      ))}
    </div>
  );
}

function parseMutation(m: string): { pos: number; aa: string } | null {
  const match = /^([A-Z])(\d+)([A-Z])$/.exec(m);
  if (!match) return null; // multi-substitution or malformed — no single cell
  return { pos: parseInt(match[2], 10), aa: match[3] };
}
