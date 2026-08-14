"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import dynamic from "next/dynamic";
import { EffectHeatmap } from "@/components/EffectHeatmap";
import { HowItWorks } from "@/components/HowItWorks";
import { PredictionForm } from "@/components/PredictionForm";
import { SingleScoreCard } from "@/components/SingleScoreCard";
import { StructureTrack } from "@/components/StructureTrack";
import { Term } from "@/components/Term";
import { structureFileUrl } from "@/lib/api";
import { parseShareUrl, writeShareUrl } from "@/lib/urlState";
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
  // Measured on the deployed CPU worker: ~2.4s per residue, because scoring
  // needs one masked forward pass per position. A 150-residue protein takes
  // about six minutes from cold; the demo proteins are pre-scored and return
  // instantly. Promising "about a minute" here was simply wrong.
  running:
    "Scoring with ESM-2. Every position gets its own masked forward pass, so a protein nobody has run before takes a few minutes on CPU. It's cached afterwards, and the examples above are already warm.",
};

export default function Home() {
  const p = usePrediction();
  const [input, setInput] = useState("");
  const [mutation, setMutation] = useState("");

  // Run whatever a shared link asked for, once.
  //
  // The latch is load-bearing, not defensive: reactStrictMode remounts every
  // component in development, so a bare mount effect fires twice, and
  // usePrediction has no in-flight guard of its own — the UI is normally
  // protected only because the submit button and example chips disable
  // themselves while busy, and this path bypasses both.
  const autoRan = useRef(false);
  useEffect(() => {
    if (autoRan.current) return;
    autoRan.current = true;

    const shared = parseShareUrl(window.location.search);
    if (!shared) return;
    setInput(shared.params.input);
    setMutation(shared.params.mutation);
    if (shared.autoRun) {
      p.run(shared.params.input, shared.params.mutation);
    }
    // p.run is stable (useCallback with no deps) and this must run exactly
    // once regardless.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = (nextInput: string, nextMutation: string) => {
    writeShareUrl({ input: nextInput, mutation: nextMutation });
    p.run(nextInput, nextMutation);
  };

  // A cell click changes which mutation is on screen without going through the
  // form, so the URL has to follow it too or a shared link would point at
  // whatever was last typed rather than what the page is showing.
  const selectCell = (clicked: string) => {
    setMutation(clicked);
    writeShareUrl({ input, mutation: clicked });
    p.rescore(clicked);
  };

  const single = p.result?.single ?? null;
  // Memoised because parseMutation returns a fresh object on every render, and
  // an unstable `highlight` prop re-fires the heatmap's draw-and-scroll effect.
  // Harmless while nothing re-rendered after a result landed; not harmless once
  // clicking a cell updates state.
  const highlight = useMemo(
    () => (single ? parseMutation(single.mutation) : null),
    [single],
  );
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
        <PredictionForm
          phase={p.phase}
          onSubmit={submit}
          input={input}
          mutation={mutation}
          onInputChange={setInput}
          onMutationChange={setMutation}
        />
      </section>

      {busy && (
        <div className="mt-6 flex items-start gap-3 text-sm text-muted">
          <span className="mt-1 h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-border border-t-ink" />
          <div>
            <div>{PHASE_TEXT[p.phase]}</div>
            {p.cached === false && p.resolved && (
              <div className="mt-1 text-xs">
                {p.resolved.length} residues, never scored before. Rough
                estimate: <strong>{estimateMinutes(p.resolved.length)}</strong>.
                You can leave this open; the result is cached once it finishes.
              </div>
            )}
          </div>
        </div>
      )}

      {p.phase === "error" && (
        <div className="mt-6 rounded-md border border-damaging/30 bg-damaging/5 px-4 py-3 text-sm">
          <div className="text-damaging">{p.error}</div>
          {p.suggestions && p.suggestions.length > 0 && (
            <div className="mt-3 space-y-2">
              {p.suggestions.map((s) => (
                <div key={s.input} className="flex items-baseline gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setInput(s.input);
                      setMutation("");
                      submit(s.input, "");
                    }}
                    className="shrink-0 rounded-full border border-ink/30 bg-surface-raised px-3 py-1 text-xs transition-colors hover:bg-ink hover:text-surface-raised"
                  >
                    {s.label}
                  </button>
                  <span className="text-xs text-muted">{s.reason}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {p.resolved && p.mutation && p.resolved.mutation_valid === false && (
        <div className="mt-6 rounded-md border border-border bg-surface-raised px-4 py-3 text-sm">
          <div>
            <span className="font-mono">{p.mutation}</span> doesn&apos;t fit
            this sequence.{" "}
            <span className="text-muted">
              {p.resolved.mutation_explanation ?? p.resolved.mutation_error}
            </span>
          </div>
          {p.resolved.mutation_suggestions.length > 0 && (
            <div className="mt-3 space-y-2">
              {p.resolved.mutation_suggestions.map((s) => (
                <div key={s.mutation} className="flex items-baseline gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      const next = p.resolved!.uniprot_id ?? input;
                      setMutation(s.mutation);
                      submit(next, s.mutation);
                    }}
                    className="shrink-0 rounded-full border border-ink/30 px-3 py-1 font-mono text-xs transition-colors hover:bg-ink hover:text-surface-raised"
                  >
                    Try {s.mutation}
                  </button>
                  <span className="text-xs text-muted">{s.reason}</span>
                </div>
              ))}
            </div>
          )}
          <div className="mt-3 text-xs text-muted">
            Showing the full effect map meanwhile.
          </div>
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
                fileUrl={structureFileUrl(
                  p.result.sequence_hash,
                  p.resolved?.structure_provider,
                )}
                perResidueImpact={p.result.per_residue_impact}
                mutation={single?.mutation ?? null}
                sequenceHash={p.result.sequence_hash}
                provider={p.resolved?.structure_provider ?? null}
              />
            </Reveal>
          )}
          <Reveal delay={0.15}>
            <EffectHeatmap
              effectMap={p.result.effect_map}
              highlight={highlight}
              onSelectCell={selectCell}
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

/**
 * Rough wall-clock for scoring a protein that isn't cached.
 *
 * Measured against the deployed CPU worker: scoring is one masked forward
 * pass per residue, which came out around 2.4 s/residue on 4 vCPU. The worker
 * now runs 8, so this halves that and rounds up, plus a fixed minute or so of
 * cold start (container boot and pulling the model weights). Deliberately
 * vague wording, since the real figure moves with instance warmth.
 */
function estimateMinutes(length: number): string {
  const minutes = 1 + (length * 1.2) / 60;
  if (minutes < 2) return "a minute or two";
  if (minutes < 10) return `around ${Math.round(minutes)} minutes`;
  return `${Math.round(minutes / 5) * 5} minutes or more`;
}

function parseMutation(m: string): { pos: number; aa: string } | null {
  const match = /^([A-Z])(\d+)([A-Z])$/.exec(m);
  if (!match) return null; // multi-substitution or malformed — no single cell
  return { pos: parseInt(match[2], 10), aa: match[3] };
}
