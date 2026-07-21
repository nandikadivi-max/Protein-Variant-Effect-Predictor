import type { SingleScore, VariantAnnotation } from "@/lib/types";
import { LABEL_COLOR, LABEL_TEXT } from "@/lib/color";

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
          <span className="text-muted">ESM-2 log-likelihood ratio</span>
          <div className="font-mono text-lg">{single.llr.toFixed(2)}</div>
        </div>
        <p className="max-w-xs text-xs text-muted">
          Lower (more negative) means the model finds the mutant residue far
          less likely than wild type — evidence the substitution is disruptive.
        </p>
      </div>

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

function predColor(prediction: string | null): string {
  const v = (prediction ?? "").toLowerCase();
  if (/patho|deleter|damag/.test(v)) return "#B91C1C";
  if (/benign|toler/.test(v)) return "#1D4ED8";
  return "#57534E";
}
