import type { SingleScore, VariantAnnotation } from "@/lib/types";
import { LABEL_COLOR, LABEL_TEXT } from "@/lib/color";
import { describeMutation } from "@/lib/glossary";
import { Term } from "@/components/Term";

interface Props {
  single: SingleScore;
  annotation: VariantAnnotation | null;
}

export function SingleScoreCard({ single, annotation }: Props) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-muted">
            Predicted effect
          </div>
          <div className="mt-1 font-mono text-2xl font-semibold">
            {single.mutation}
          </div>
          {describeMutation(single.mutation) && (
            <div className="mt-0.5 text-xs text-muted">
              {describeMutation(single.mutation)}
            </div>
          )}
        </div>
        <span
          className="rounded-full px-3 py-1 text-sm font-medium text-white"
          style={{ backgroundColor: LABEL_COLOR[single.label] }}
        >
          {LABEL_TEXT[single.label]}
        </span>
      </div>

      <div className="mt-4 flex items-center gap-6 text-sm">
        <div>
          <span className="text-muted">
            ESM-2 <Term k="llr">log-likelihood ratio</Term>
          </span>
          <div className="font-mono text-lg">{single.llr.toFixed(2)}</div>
        </div>
        <p className="max-w-sm text-xs text-muted">
          <span className="font-mono">
            log P(mutant) − log P(<Term k="wild type">wild type</Term>)
          </span>{" "}
          at this position. More negative means the model finds the substitute
          far less plausible than the original letter, which is evidence the
          change is disruptive.
        </p>
      </div>

      {single.mutation.includes(":") && (
        <p className="mt-3 text-xs text-muted">
          This score is the sum of each substitution scored on its own, which
          assumes they act independently. Residues that interact can behave
          very differently together than apart, so read a combined score as a
          rough guide rather than a prediction about the double mutant.
        </p>
      )}

      {single.percentile != null && (
        <div className="mt-4 border-t border-border pt-4">
          <div className="text-xs font-medium uppercase tracking-wide text-muted">
            <Term k="percentile">How it ranks</Term>
          </div>
          <p className="mt-2 text-sm">
            More damaging than{" "}
            <span className="font-mono font-medium">
              {single.percentile.toFixed(0)}%
            </span>{" "}
            of every possible substitution in this protein.
          </p>
          <PercentileBar percentile={single.percentile} />
          <p className="mt-2 text-xs text-muted">
            Ranked against all 19 alternatives at every position. This is
            relative to this protein: somewhere highly constrained, even a mild
            change can land near the top.
          </p>
        </div>
      )}

      {annotation && (
        <div className="mt-4 border-t border-border pt-4">
          <div className="text-xs font-medium uppercase tracking-wide text-muted">
            Known clinical annotation
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            {annotation.clinical_significance ? (
              <span className="font-medium">
                {annotation.clinical_significance}
              </span>
            ) : (
              <span className="text-muted">No clinical classification</span>
            )}
            {annotation.sources.length > 0 && (
              <span className="text-xs text-muted">
                · {annotation.sources.join(", ")}
              </span>
            )}
          </div>
          {annotation.significances.length > 1 && (
            <p className="mt-2 max-w-lg text-xs text-muted">
              Submitted as{" "}
              <span className="text-ink">
                {annotation.significances.join(", ")}
              </span>{" "}
              by different sources. Usually this means more than one DNA change
              produces the same amino-acid swap, and they were not all
              interpreted the same way, so the databases genuinely disagree
              here rather than one of them being out of date.
            </p>
          )}
          <Discordance single={single} annotation={annotation} />
          {annotation.diseases.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {annotation.diseases.slice(0, 6).map((d) => (
                <span
                  key={d}
                  className="rounded border border-border px-2 py-0.5 text-xs text-muted"
                >
                  {d}
                </span>
              ))}
            </div>
          )}

          {annotation.predictions.length > 0 && (
            <div className="mt-3">
              <div className="text-xs font-medium uppercase tracking-wide text-muted">
                Predictors
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {annotation.predictions.map((p) => (
                  <span
                    key={p.algorithm}
                    className="rounded-md border border-border px-2.5 py-1 text-xs"
                  >
                    <span className="text-muted">{p.algorithm}</span>{" "}
                    <span
                      className="font-medium"
                      style={{ color: predColor(p.prediction) }}
                    >
                      {p.prediction ?? "—"}
                    </span>
                    {p.score != null && (
                      <span className="text-muted"> ({p.score.toFixed(2)})</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Say so when the model and the clinical databases disagree.
 *
 * Hiding this would be the dishonest choice, and it is also the most
 * interesting thing on the page: the gap is not noise, it tracks disease
 * mechanism. A zero-shot language model scores how ordinary a sequence looks,
 * so it finds variants that break a fold or hit a conserved site and misses
 * the ones that leave the protein looking unremarkable. Sickle-cell is the
 * standing example, which is why it is a demo chip rather than one quietly
 * swapped out for a variant that scores better.
 *
 * Deliberately keyed off the two labels rather than a list of known variants,
 * so it holds for any protein someone types in.
 */
function Discordance({
  single,
  annotation,
}: {
  single: SingleScore;
  annotation: VariantAnnotation;
}) {
  const call = (annotation.clinical_significance ?? "").toLowerCase();
  // A conflict is already explained above; don't stack two caveats.
  if (!call || call.startsWith("conflicting")) return null;

  const clinical = /pathogenic/.test(call) ? 1 : /benign/.test(call) ? -1 : 0;
  const model =
    single.label === "likely_damaging"
      ? 1
      : single.label === "likely_tolerated"
        ? -1
        : 0;

  if (clinical === 1 && model !== 1) {
    return (
      <p className="mt-3 max-w-lg rounded-md border border-border bg-surface px-3 py-2 text-xs leading-relaxed text-muted">
        <span className="font-medium text-ink">
          The databases and the model disagree here.
        </span>{" "}
        ESM-2 judges how plausible a sequence looks next to evolution, so it
        catches substitutions that destabilise a fold or land on a conserved
        active site. Variants that leave the folded protein looking fairly
        ordinary and cause disease some other way are its blind spot.
        Sickle-cell haemoglobin is the textbook case: the swap puts a sticky
        patch on the surface that makes deoxygenated haemoglobin polymerise
        into fibres, and nothing about that looks unusual to a model asking
        only whether the sequence is evolutionarily normal.
      </p>
    );
  }

  if (clinical === -1 && model === 1) {
    return (
      <p className="mt-3 max-w-lg rounded-md border border-border bg-surface px-3 py-2 text-xs leading-relaxed text-muted">
        <span className="font-medium text-ink">
          The model scores this lower than the clinical call.
        </span>{" "}
        A low score means the substitution is rare against evolution, which is
        not the same as harmful. Positions can be well conserved across species
        and still tolerate change in humans.
      </p>
    );
  }

  return null;
}

/**
 * Where this mutation sits among every substitution in the protein.
 *
 * A bar rather than a number alone because "94%" invites being read as a
 * probability of being damaging, which is not what a zero-shot LLR rank means.
 * Seeing the marker's position against the full width makes it obvious this is
 * a ranking within one protein.
 */
function PercentileBar({ percentile }: { percentile: number }) {
  const clamped = Math.min(100, Math.max(0, percentile));
  return (
    <div className="mt-3">
      <div className="relative h-1.5 rounded-full bg-gradient-to-r from-tolerated/30 via-border to-damaging/60">
        <span
          className="absolute top-1/2 h-3 w-[3px] -translate-y-1/2 rounded-full bg-ink"
          style={{ left: `calc(${clamped}% - 1.5px)` }}
        />
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-muted">
        <span>most tolerated</span>
        <span>most damaging</span>
      </div>
    </div>
  );
}

function predColor(prediction: string | null): string {
  const v = (prediction ?? "").toLowerCase();
  if (/patho|deleter|damag/.test(v)) return "#B91C1C";
  if (/benign|toler/.test(v)) return "#1D4ED8";
  return "#57534E";
}
