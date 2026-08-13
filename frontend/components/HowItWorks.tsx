"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

/**
 * The explainer. Collapsed by default so it never gets in the way of someone
 * who came to use the tool, but one click from the top of the page for someone
 * who landed here without the background.
 *
 * Written for a reader who knows machine learning but not molecular biology —
 * that is the audience most likely to arrive from a portfolio link, and the
 * one for whom "zero-shot missense variant scoring" parses as noise. The
 * framing leans on the fact that this genuinely is a masked language model,
 * so most of it can be explained in vocabulary they already own.
 */
export function HowItWorks() {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-ink"
      >
        <svg
          viewBox="0 0 12 12"
          className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`}
          aria-hidden
        >
          <path
            d="M4 2.5 L8 6 L4 9.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        New here? How this works
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="mt-4 grid gap-5 rounded-lg border border-border bg-surface-raised p-5 text-sm leading-relaxed sm:grid-cols-2">
              <Block n="1" title="A protein is a string">
                Proteins are chains of{" "}
                <strong className="font-medium">amino acids</strong>. There are
                exactly 20 of them and each one is written as a single letter,
                so a protein is a string over a 20-letter alphabet:{" "}
                <code className="font-mono text-xs">MEEPQSDPSV…</code> That
                string folds into a 3D shape, and the shape is what does the
                work.
              </Block>

              <Block n="2" title="Change one letter. Does it still work?">
                Swap a single letter and the protein might be completely fine,
                or it might not fold at all. In humans that difference is often
                the difference between healthy and sick. There are 20 possible
                letters at each of thousands of positions, and almost none of
                those combinations has ever been measured in a lab.
              </Block>

              <Block n="3" title="ESM-2 is BERT for proteins">
                Same architecture, same masked-token objective. The corpus is
                65M protein sequences instead of text. Mask a position, predict
                what belongs there from the surrounding context. This one has
                650M parameters.
              </Block>

              <Block n="4" title="The score is just masked-token likelihood">
                To score a mutation, mask that position, run the model once, and
                read two numbers off the output distribution:
                <span className="mt-2 block rounded bg-surface px-3 py-2 font-mono text-xs">
                  LLR = log P(mutant) − log P(wild&nbsp;type)
                </span>
                <span className="mt-2 block">
                  Strongly negative means the model is confident the original
                  letter belongs there and the substitute does not.
                </span>
              </Block>

              <Block n="5" title="Why this is “zero-shot”">
                The model has never seen a labelled mutation. It only learned
                which sequences look plausible, and that turns out to be enough,
                because{" "}
                <strong className="font-medium">
                  evolution did the labelling for us
                </strong>
                . Sequences carrying broken mutations never survived to be
                sequenced, so they simply aren&apos;t in the training data. The
                model picks up conservation without anyone annotating it.
              </Block>

              <Block n="6" title="Does it actually work?">
                Validated on{" "}
                <a
                  href="https://proteingym.org"
                  target="_blank"
                  rel="noreferrer"
                  className="border-b border-dotted border-muted/60 hover:text-ink"
                >
                  ProteinGym
                </a>
                , which collects experiments where labs measured thousands of
                mutations directly. Mean Spearman correlation of{" "}
                <span className="font-mono">0.447</span> between this score and
                real measured fitness, which is in line with published numbers
                for this model size.
              </Block>
            </div>

            <p className="mt-3 text-xs text-muted">
              Reading the notation:{" "}
              <span className="font-mono text-ink">R175H</span> means position
              175 normally holds arginine (R) and has been replaced with
              histidine (H). Positions here follow UniProt&apos;s canonical
              numbering, which counts the starting methionine. Clinical names
              often count the mature protein instead, after that methionine is
              removed, so they can sit one lower: sickle-cell haemoglobin is
              famously <span className="font-mono">E6V</span> but is{" "}
              <span className="font-mono text-ink">E7V</span> here. Everything
              on this page is a research tool, not a clinical one.
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Block({
  n,
  title,
  children,
}: {
  n: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-xs text-muted">{n}</span>
        <h3 className="font-medium">{title}</h3>
      </div>
      <p className="mt-1.5 text-muted">{children}</p>
    </div>
  );
}
