"use client";

import { useRef } from "react";
import type { StructureContext } from "@/lib/types";
import { useScrollSync } from "@/lib/useScrollSync";
import { AXIS_W, CELL_W } from "@/lib/grid";

// A compact per-residue track shown under the heatmap: secondary structure
// (helix / strand / coil) plus a buried/exposed strip. Shares the heatmap's
// grid geometry and scroll position (see lib/grid and lib/useScrollSync) so a
// column here refers to the same residue as the column above it.

// Row heights, shared by the strips and their fixed labels so the two stay
// vertically aligned.
const SS_H = 14;
const BURIED_H = 8;

const SS_COLOR: Record<string, string> = {
  H: "#7C3AED", // helix — violet
  E: "#D97706", // strand — amber
  C: "#D6D3D1", // coil — light stone
};
const SS_LABEL: Record<string, string> = {
  H: "Helix",
  E: "Strand",
  C: "Coil",
};

export function StructureTrack({ structure }: { structure: StructureContext }) {
  const { secondary_structure: ss, buried } = structure;
  const width = ss.length * CELL_W;

  // Same residue grid as the heatmap, so follow its horizontal position —
  // otherwise the heatmap centres on the queried mutation while this track
  // still shows position 1, and the columns no longer refer to each other.
  const scrollRef = useRef<HTMLDivElement>(null);
  useScrollSync("residue-grid", scrollRef);

  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="mb-3 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-medium">
            Structural context <span className="text-muted">· DSSP</span>
          </h3>
          <p className="mt-0.5 max-w-xl text-xs text-muted">
            Where each position sits in the folded shape. <b>SS</b> is the local
            fold — helix, strand, or neither. <b>Buried</b> marks positions
            packed inside rather than on the surface; those are the ones that
            usually tolerate change least.
          </p>
        </div>
        <Legend />
      </div>
      {/* Labels sit OUTSIDE the scroll container, mirroring the heatmap's fixed
          amino-acid axis — inside it they would scroll away with the data. The
          gutter is the same width in both, so residue N lands at the same x. */}
      <div className="flex">
        <div
          className="shrink-0 pr-1 text-right font-mono text-[10px] text-muted"
          style={{ width: AXIS_W }}
        >
          <div style={{ height: SS_H, lineHeight: `${SS_H}px` }}>SS</div>
          <div style={{ height: BURIED_H, lineHeight: `${BURIED_H}px` }}>
            Buried
          </div>
        </div>
        <div ref={scrollRef} className="scroll-slim overflow-x-auto">
          <div style={{ width }}>
            <div className="flex leading-none">
              {ss.map((s, i) => (
                <span
                  key={i}
                  title={`${i + 1} · ${SS_LABEL[s] ?? "Coil"}`}
                  style={{
                    width: CELL_W,
                    height: SS_H,
                    background: SS_COLOR[s] ?? SS_COLOR.C,
                  }}
                  className="inline-block"
                />
              ))}
            </div>
            <div className="flex leading-none">
              {buried.map((b, i) => (
                <span
                  key={i}
                  title={`${i + 1} · ${b ? "Buried" : "Exposed"}`}
                  style={{
                    width: CELL_W,
                    height: BURIED_H,
                    background: b ? "#1C1917" : "#E7E5E4",
                  }}
                  className="inline-block"
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex items-center gap-3 text-[10px] text-muted">
      {(["H", "E", "C"] as const).map((s) => (
        <span key={s} className="flex items-center gap-1">
          <span
            className="inline-block h-2 w-2 rounded-sm"
            style={{ background: SS_COLOR[s] }}
          />
          {SS_LABEL[s]}
        </span>
      ))}
    </div>
  );
}
