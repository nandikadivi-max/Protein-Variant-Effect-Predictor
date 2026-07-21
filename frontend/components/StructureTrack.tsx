"use client";

import type { StructureContext } from "@/lib/types";

// A compact per-residue track shown under the heatmap: secondary structure
// (helix / strand / coil) plus a buried/exposed strip. Aligned to the same
// 14px-per-residue grid as the heatmap so columns line up.
const CELL_W = 14;

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

  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium">
          Structural context <span className="text-muted">· DSSP</span>
        </h3>
        <Legend />
      </div>
      <div className="scroll-slim overflow-x-auto">
        <div style={{ width }}>
          <Row label="SS">
            {ss.map((s, i) => (
              <span
                key={i}
                title={`${i + 1} · ${SS_LABEL[s] ?? "Coil"}`}
                style={{ width: CELL_W, background: SS_COLOR[s] ?? SS_COLOR.C }}
                className="inline-block h-3.5"
              />
            ))}
          </Row>
          <Row label="Buried">
            {buried.map((b, i) => (
              <span
                key={i}
                title={`${i + 1} · ${b ? "Buried" : "Exposed"}`}
                style={{
                  width: CELL_W,
                  background: b ? "#1C1917" : "#E7E5E4",
                }}
                className="inline-block h-2"
              />
            ))}
          </Row>
        </div>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-12 shrink-0 text-right font-mono text-[10px] text-muted">
        {label}
      </span>
      <div className="flex leading-none">{children}</div>
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
