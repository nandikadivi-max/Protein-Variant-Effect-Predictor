"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AA_ORDER } from "@/lib/types";
import { llrColor } from "@/lib/color";
import { useScrollSync } from "@/lib/useScrollSync";
import { AXIS_W, CELL_W } from "@/lib/grid";

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
  /** Called with a mutation string like "R175H" when a cell is clicked. */
  onSelectCell?: (mutation: string) => void;
}

export function EffectHeatmap({ effectMap, highlight, onSelectCell }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const L = effectMap.length;

  // Keeps the DSSP track below locked to the same residue columns.
  useScrollSync("residue-grid", scrollRef);

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

    // Bring the queried mutation into view, but only if it isn't already.
    // Done here, right after the canvas is sized, so reading the container
    // forces a reflow and the scroll actually applies.
    //
    // Scroll-INTO-view rather than always-centre: a cell the user just clicked
    // is by definition on screen, so an unconditional recentre would yank the
    // grid out from under the pointer and leave the tooltip describing a cell
    // that is no longer there. A mutation typed into the form is usually off
    // screen and still gets centred exactly as before.
    const container = scrollRef.current;
    if (highlight && container) {
      const cellLeft = (highlight.pos - 1) * CELL_W;
      const viewLeft = container.scrollLeft;
      const viewRight = viewLeft + container.clientWidth;
      const visible = cellLeft >= viewLeft && cellLeft + CELL_W <= viewRight;
      if (!visible) {
        container.scrollLeft = Math.max(0, cellLeft - container.clientWidth / 2);
      }
    }
  }, [effectMap, highlight, L]);

  /** Pixel -> cell, shared by hover and click so they can never disagree. */
  function cellAt(e: React.MouseEvent<HTMLCanvasElement>): Hover | null {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top - RULER_H;
    const pos = Math.floor(x / CELL_W);
    const aa = Math.floor(y / CELL_H);
    if (pos < 0 || pos >= L || aa < 0 || aa >= 20) return null;
    return {
      x,
      y: y + RULER_H,
      pos: pos + 1,
      aa: AA_ORDER[aa],
      wt: wt[pos],
      llr: effectMap[pos][aa],
    };
  }

  function onMove(e: React.MouseEvent<HTMLCanvasElement>) {
    setHover(cellAt(e));
  }

  function onClick(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!onSelectCell) return;
    const cell = cellAt(e);
    if (!cell) return;
    // The wildtype cell is the residue against itself. The server would happily
    // accept it — Variant.parse("R175R") is valid, scores 0.0, and classifies
    // as tolerated — producing a nonsense "R175R · Likely tolerated" card. So
    // it is refused here.
    if (cell.aa === cell.wt) return;
    onSelectCell(`${cell.wt}${cell.pos}${cell.aa}`);
  }

  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="mb-3 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-medium">
            Variant effect map{" "}
            <span className="text-muted">
              · {L} positions × 20 amino acids ={" "}
              {(L * 20).toLocaleString()} predictions
            </span>
          </h3>
          <p className="mt-0.5 text-xs text-muted">
            Every substitution that could be made anywhere in this protein. Each
            column is a position, each row an amino acid; dots mark the original
            letter. Solid red columns are positions that tolerate almost
            nothing.
            {onSelectCell && (
              <>
                {" "}
                <span className="text-ink">Click any cell</span> to score that
                substitution.
              </>
            )}
          </p>
        </div>
        <Legend />
      </div>
      <div className="flex">
        {/* Fixed amino-acid axis */}
        <div
          className="shrink-0 pr-1 text-right font-mono text-[10px] text-muted"
          style={{ paddingTop: RULER_H, width: AXIS_W }}
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
            onClick={onClick}
            // Only advertise clickability over a cell that would actually do
            // something: not over the wildtype cell, and not at all when no
            // handler is wired up.
            style={{
              cursor:
                onSelectCell && hover && hover.aa !== hover.wt
                  ? "pointer"
                  : "default",
            }}
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
