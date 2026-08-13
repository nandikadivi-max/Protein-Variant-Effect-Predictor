"use client";

import { motion } from "framer-motion";
import dynamic from "next/dynamic";
import { EffectHeatmap } from "@/components/EffectHeatmap";
import { HowItWorks } from "@/components/HowItWorks";
import { PredictionForm } from "@/components/PredictionForm";
import { SingleScoreCard } from "@/components/SingleScoreCard";
import { StructureTrack } from "@/components/StructureTrack";
import { Term } from "@/components/Term";
import { structureFileUrl } from "@/lib/api";
import { usePrediction } from "@/lib/usePrediction";

// Mol* is client-only (WebGL, no SSR).
const StructureViewer = dynamic(
  () => import("@/components/StructureViewer").then((m) => m.StructureViewer),
  { ssr: false },
);

const PHASE_TEXT: Record<string, string> = {
  resolving: "Looking up the sequence…",
  queued: "Queued for scoring…",
  // A protein nobody has scored before needs a full forward pass per position,
  // so say so rather than leaving the user watching an unexplained spinner.
  running:
    "Running ESM-2, one masked forward pass per position. The first time for a given protein takes about a minute, then it's cached.",
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
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
          A protein is a string over a 20-letter alphabet. Change one letter and
          it might work fine, or it might not fold at all. This scores that
          change using{" "}
          <a
            href="https://github.com/facebookresearch/esm"
            target="_blank"
            rel="noreferrer"
            className="border-b border-dotted border-muted/60 hover:text-ink"
          >
            ESM-2
          </a>
          , a masked language model trained on 65M protein sequences. It was{" "}
          <em className="not-italic text-ink">
            never shown a single mutation outcome
          </em>
          .
        </p>
        <HowItWorks />
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
          <Reveal>
            <ResolvedMeta result={p.result} source={p.resolved?.source} />
          </Reveal>
          {single && (
            <Reveal delay={0.05}>
              <SingleScoreCard
                single={single}
                annotation={p.result.annotation}
              />
            </Reveal>
          )}
          {p.resolved?.has_structure && (
            <Reveal delay={0.1}>
              <StructureViewer
                fileUrl={structureFileUrl(p.result.sequence_hash)}
                perResidueImpact={p.result.per_residue_impact}
                mutation={single?.mutation ?? null}
              />
            </Reveal>
          )}
          <Reveal delay={0.15}>
            <EffectHeatmap
              effectMap={p.result.effect_map}
              highlight={highlight}
            />
          </Reveal>
          {p.result.structure && (
            <Reveal delay={0.2}>
              <StructureTrack structure={p.result.structure} />
            </Reveal>
          )}
        </div>
      )}

      <footer className="mt-16 space-y-2 border-t border-border pt-6 text-xs text-muted">
        <p>
          Scores from ESM-2 650M (<Term k="zero-shot">zero-shot</Term>{" "}
          masked-marginal) · structures from{" "}
          <Term k="alphafold">AlphaFold</Term> and{" "}
          <Term k="pdb">RCSB PDB</Term> · fold features from{" "}
          <Term k="dssp">DSSP</Term> · clinical annotations from the EBI
          Proteins API (<Term k="clinvar">ClinVar</Term>, Ensembl, UniProt).
        </p>
        <p>
          <a
            href="https://github.com/nandikadivi-max/Protein-Variant-Effect-Predictor"
            target="_blank"
            rel="noreferrer"
            className="border-b border-dotted border-muted/60 hover:text-ink"
          >
            Source on GitHub
          </a>{" "}
          · Research tool, not for clinical use.
        </p>
      </footer>
    </main>
  );
}

function Reveal({
  children,
  delay = 0,
}: {
  children: React.ReactNode;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay, ease: "easeOut" }}
    >
      {children}
    </motion.div>
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
