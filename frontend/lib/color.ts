// Restrained diverging scale for log-likelihood ratios.
//   negative LLR  -> damaging  -> red
//   ~0            -> neutral   -> near-white
//   positive LLR  -> tolerated -> blue
// Most cells are <= 0 (wild type is usually the likeliest residue), so the
// map reads mostly white->red with occasional blue.

const RED = [185, 28, 28]; // damaging  (#B91C1C)
const PALE = [245, 245, 244]; // ~white  (surface-ish)
const BLUE = [29, 78, 216]; // tolerated (#1D4ED8)

const CLAMP = 8; // LLR magnitude that saturates the scale

function lerp(a: number[], b: number[], t: number): string {
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

export function llrColor(llr: number): string {
  if (llr <= 0) {
    const t = Math.min(1, -llr / CLAMP); // 0 at llr=0, 1 at llr<=-CLAMP
    return lerp(PALE, RED, t);
  }
  const t = Math.min(1, llr / 2); // positives are small; saturate quickly
  return lerp(PALE, BLUE, t);
}

export const LABEL_COLOR: Record<string, string> = {
  likely_damaging: "#B91C1C",
  uncertain: "#57534E",
  likely_tolerated: "#1D4ED8",
};

export const LABEL_TEXT: Record<string, string> = {
  likely_damaging: "Likely damaging",
  uncertain: "Uncertain",
  likely_tolerated: "Likely tolerated",
};
