"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AA_ORDER } from "@/lib/types";
import { llrColor } from "@/lib/color";

const CELL_W = 14;
const CELL_H = 16;
const RULER_H = 18;
const GRID_H = CELL_H * 20;

interface Hover {
  x: number;
  y: number;
  pos: number; // 1-based
  aa: string;
  wt: string;
  llr: number;
}

interface Props {
  effectMap: number[][]; // L x 20
  highlight?: { pos: number; aa: string } | null;
}

export function EffectHeatmap({ effectMap, highlight }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const L = effectMap.length;

  // Wild-type residue per position = the column whose LLR is exactly 0.
  const wt = useMemo(
    () =>
      effectMap.map((row) => {
        const i = row.findIndex((v) => v === 0);
        return i >= 0 ? AA_ORDER[i] : "?";
      }),
    [effectMap],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const width = L * CELL_W;
    const height = RULER_H + GRID_H;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    // Cells
    for (let pos = 0; pos < L; pos++) {
      const col = effectMap[pos];
      for (let aa = 0; aa < 20; aa++) {
        ctx.fillStyle = llrColor(col[aa]);
        ctx.fillRect(pos * CELL_W, RULER_H + aa * CELL_H, CELL_W, CELL_H);
        if (col[aa] === 0) {
          // Wild-type marker: a small dark dot.
          ctx.fillStyle = "rgba(28,25,23,0.55)";
          ctx.beginPath();
          ctx.arc(
            pos * CELL_W + CELL_W / 2,
            RULER_H + aa * CELL_H + CELL_H / 2,
            1.6,
            0,
            Math.PI * 2,
          );
          ctx.fill();
        }
      }
    }

    // Ruler ticks every 25 residues.
    ctx.fillStyle = "#78716C";
    ctx.font = "10px var(--font-mono), monospace";
    ctx.textBaseline = "middle";
    for (let pos = 0; pos < L; pos++) {
      const p = pos + 1;
      if (p === 1 || p % 25 === 0) {
        ctx.fillRect(pos * CELL_W + CELL_W / 2, RULER_H - 5, 1, 4);
        ctx.fillText(String(p), pos * CELL_W + CELL_W / 2 + 2, RULER_H - 9);
      }
    }

    // Highlight the queried mutation cell.
    if (highlight) {
      const aaIdx = AA_ORDER.indexOf(highlight.aa);
      if (highlight.pos >= 1 && highlight.pos <= L && aaIdx >= 0) {
        ctx.strokeStyle = "#1C1917";
        ctx.lineWidth = 2;
        ctx.strokeRect(
          (highlight.pos - 1) * CELL_W + 1,
          RULER_H + aaIdx * CELL_H + 1,
          CELL_W - 2,
          CELL_H - 2,
        );
      }
    }

    // Bring the queried mutation into view — deferred to the next frame so the
    // canvas has its final width and the container is actually scrollable.
    // Center the queried mutation. Done here, right after the canvas is sized,
    // so reading the container forces a reflow and the scroll actually applies.
    const container = scrollRef.current;
    if (highlight && container) {
      const target = (highlight.pos - 1) * CELL_W - container.clientWidth / 2;
      container.scrollLeft = Math.max(0, target);
    }
  }, [effectMap, highlight, L]);

  function onMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top - RULER_H;
    const pos = Math.floor(x / CELL_W);
    const aa = Math.floor(y / CELL_H);
    if (pos < 0 || pos >= L || aa < 0 || aa >= 20) {
      setHover(null);
      return;
    }
    setHover({
      x,
      y: y + RULER_H,
      pos: pos + 1,
      aa: AA_ORDER[aa],
      wt: wt[pos],
      llr: effectMap[pos][aa],
    });
  }

  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium">
          Variant effect map{" "}
          <span className="text-muted">· {L} positions × 20 residues</span>
        </h3>
        <Legend />
      </div>
      <div className="flex">
        {/* Fixed amino-acid axis */}
        <div
          className="shrink-0 pr-1 text-right font-mono text-[10px] text-muted"
          style={{ paddingTop: RULER_H }}
        >
          {AA_ORDER.map((a) => (
            <div key={a} style={{ height: CELL_H, lineHeight: `${CELL_H}px` }}>
              {a}
            </div>
          ))}
        </div>
        {/* Scrollable heatmap */}
        <div ref={scrollRef} className="scroll-slim relative overflow-x-auto">
          <canvas
            ref={canvasRef}
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          />
          {hover && (
            <div
              className="pointer-events-none absolute z-10 whitespace-nowrap rounded bg-ink px-2 py-1 font-mono text-[11px] text-surface-raised"
              style={{
                left: Math.min(hover.x + 10, (L - 6) * CELL_W),
                top: hover.y + 10,
              }}
            >
              {hover.wt}
              {hover.pos}
              {hover.aa} · LLR {hover.llr.toFixed(2)}
              {hover.aa === hover.wt ? " (wild type)" : ""}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex items-center gap-2 text-[10px] text-muted">
      <span>damaging</span>
      <div
        className="h-2 w-24 rounded"
        style={{
          background:
            "linear-gradient(90deg, #B91C1C 0%, #F5F5F4 62%, #1D4ED8 100%)",
        }}
      />
      <span>tolerated</span>
    </div>
  );
}
