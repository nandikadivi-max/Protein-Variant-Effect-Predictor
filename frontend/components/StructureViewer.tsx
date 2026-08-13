"use client";

import { useEffect, useRef, useState } from "react";
import "molstar/build/viewer/molstar.css";
import { makeImpactColorThemeProvider } from "@/lib/impactColorTheme";
import { getStructureInfo, type SiftsSegment } from "@/lib/api";

interface Props {
  fileUrl: string;
  perResidueImpact: number[];
  /** e.g. "R175H", or "R248Q:D281N". Null hides the marker. */
  mutation?: string | null;
  /** Hash used to look up the numbering map for colouring. */
  sequenceHash: string;
}

// Three-letter to one-letter, written out rather than imported from a Mol*
// internal path so the wildtype guard below can't break on a module move.
const THREE_TO_ONE: Record<string, string> = {
  ALA: "A", ARG: "R", ASN: "N", ASP: "D", CYS: "C",
  GLN: "Q", GLU: "E", GLY: "G", HIS: "H", ILE: "I",
  LEU: "L", LYS: "K", MET: "M", PHE: "F", PRO: "P",
  SER: "S", THR: "T", TRP: "W", TYR: "Y", VAL: "V",
};

/**
 * Map label_seq_id -> one-letter residue code for the loaded model.
 *
 * The residue table exposes label_seq_id (the impact colour theme relies on
 * it) but not always the residue name, so fall back to reading the name off
 * the residue's first atom. Returns an empty map if neither is available,
 * which makes the caller mark nothing rather than mark the wrong thing.
 */
function residueCodesBySeqId(model: any): Map<number, string> {
  const out = new Map<number, string>();
  const h = model?.atomicHierarchy;
  const residues = h?.residues;
  if (!residues?.label_seq_id) return out;

  const rowCount = residues._rowCount ?? residues.label_seq_id.rowCount ?? 0;
  const offsets = h?.residueAtomSegments?.offsets;
  const readName = (i: number): string | undefined => {
    if (residues.label_comp_id) return residues.label_comp_id.value(i);
    if (h?.atoms?.label_comp_id && offsets) {
      return h.atoms.label_comp_id.value(offsets[i]);
    }
    return undefined;
  };

  for (let i = 0; i < rowCount; i++) {
    const name = readName(i);
    if (name === undefined) return new Map(); // no reliable source; guard off
    const one = THREE_TO_ONE[String(name).toUpperCase()];
    if (one) out.set(residues.label_seq_id.value(i), one);
  }
  return out;
}

/** Positions whose residue in the loaded structure really is the expected
 *  wildtype. See the guard's rationale in the marker effect below. */
function verifiedPositions(structureData: any, mutation: string): number[] {
  const codes = residueCodesBySeqId(structureData?.models?.[0]);
  if (codes.size === 0) return [];

  const out: number[] = [];
  for (const part of mutation.split(":")) {
    const m = /^([A-Z])(\d+)([A-Z])$/.exec(part.trim().toUpperCase());
    if (!m) continue;
    const [, wt, posStr] = m;
    const pos = parseInt(posStr, 10);
    if (codes.get(pos) === wt) out.push(pos);
  }
  return out;
}

// A minimal embedded Mol* viewer. Loads the PDB served by the backend and
// shows a cartoon. Per-residue impact coloring is layered on in a follow-up.
export function StructureViewer({
  fileUrl,
  perResidueImpact,
  mutation = null,
  sequenceHash,
}: Props) {
  const parent = useRef<HTMLDivElement>(null);
  const pluginRef = useRef<any>(null);
  const structureRef = useRef<any>(null);
  const [error, setError] = useState<string | null>(null);
  // Gates the marker effect below: the structure must exist before anything
  // can select a residue in it.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let disposed = false;
    setReady(false);

    (async () => {
      try {
        const [{ createPluginUI }, { renderReact18 }, { DefaultPluginUISpec }] =
          await Promise.all([
            import("molstar/lib/mol-plugin-ui"),
            import("molstar/lib/mol-plugin-ui/react18"),
            import("molstar/lib/mol-plugin-ui/spec"),
          ]);
        if (disposed || !parent.current) return;

        const spec = DefaultPluginUISpec();
        // Trim the chrome for an embedded, read-only viewer.
        spec.layout = {
          initial: {
            isExpanded: false,
            showControls: false,
            controlsDisplay: "reactive",
          },
        };

        const plugin = await createPluginUI({
          target: parent.current,
          render: renderReact18,
          spec,
        });
        // `disposed` was last checked before this await. A rapid re-query can
        // supersede this run mid-flight, and without re-checking here the
        // stale run overwrites pluginRef and builds into the same div, leaving
        // an orphaned WebGL context that nothing will ever dispose.
        if (disposed) {
          plugin.dispose();
          return;
        }
        pluginRef.current = plugin;

        // Register the per-residue impact color theme (closes over the data).
        // Each plugin instance has its own registry, so a single add is safe.
        // Colouring is by UniProt position, so an experimental structure
        // needs its author-numbering map or every residue is painted with a
        // constant offset. AlphaFold returns none and falls through to
        // identity. Failing to fetch it must not stop the structure loading.
        let segments: SiftsSegment[] = [];
        try {
          segments = (await getStructureInfo(sequenceHash)).sifts_segments ?? [];
        } catch {
          /* colour by identity numbering rather than not rendering at all */
        }
        if (disposed) return;

        const provider = makeImpactColorThemeProvider(perResidueImpact, segments);
        try {
          plugin.representation.structure.themes.colorThemeRegistry.add(
            provider as any,
          );
        } catch {
          /* already registered on this plugin */
        }

        const data = await plugin.builders.data.download(
          { url: fileUrl, isBinary: false },
          { state: { isGhost: true } },
        );
        const trajectory = await plugin.builders.structure.parseTrajectory(
          data,
          "pdb",
        );
        const model = await plugin.builders.structure.createModel(trajectory);
        const structure =
          await plugin.builders.structure.createStructure(model);
        await plugin.builders.structure.representation.addRepresentation(
          structure,
          { type: "cartoon", color: "variant-impact" as any },
        );

        structureRef.current = structure;
        if (!disposed) setReady(true);
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      }
    })();

    return () => {
      disposed = true;
      setReady(false);
      structureRef.current = null;
      pluginRef.current?.dispose?.();
      pluginRef.current = null;
    };
    // `mutation` is deliberately NOT a dependency here. This effect disposes
    // and rebuilds the whole plugin, so reacting to the mutation would tear
    // down the viewer, re-download the PDB and reset the camera every time
    // the user picks a different variant. The marker lives in its own effect.
  }, [fileUrl, perResidueImpact, sequenceHash]);

  // Mark the mutated residue(s). Separate from init so changing the mutation
  // costs one small component swap instead of a full viewer rebuild.
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;

    (async () => {
      const plugin = pluginRef.current;
      const structure = structureRef.current;
      if (!plugin || !structure) return;

      try {
        const [{ MolScriptBuilder: MS }, { Color }] = await Promise.all([
          import("molstar/lib/mol-script/language/builder"),
          import("molstar/lib/mol-util/color"),
        ]);
        if (cancelled) return;

        // The colour theme reads label_seq_id, which equals the UniProt
        // position for AlphaFold models. An RCSB entry is in author numbering
        // and Mol* never sees the SIFTS offset the backend applies, so a bare
        // positional match could land on the wrong residue. Requiring the
        // residue to actually BE the expected wildtype makes a wrong hit
        // self-evident: on a mismatch we mark nothing rather than lie.
        const structureData =
          structure.data ?? structure.cell?.obj?.data ?? null;
        const positions = mutation
          ? verifiedPositions(structureData, mutation)
          : [];

        // An empty selection makes tryCreateComponentFromExpression remove the
        // component, so clearing the mutation cleans up without extra work.
        const expression = MS.struct.generator.atomGroups({
          "residue-test": MS.core.set.has([
            MS.set(...positions),
            MS.struct.atomProperty.macromolecular.label_seq_id(),
          ]),
        });

        const component =
          await plugin.builders.structure.tryCreateComponentFromExpression(
            structure,
            expression,
            "mutation-marker", // stable key => updates in place, never stacks
            { label: mutation ? `Mutation ${mutation}` : "Mutation" },
          );
        if (cancelled || !component) return;

        await plugin.builders.structure.representation.addRepresentation(
          component,
          {
            type: "ball-and-stick",
            // Oversized on purpose. At default scale a single residue is a few
            // faint lines lost against the cartoon, and a buried one like
            // TP53 R175 is invisible entirely. Scaled up it reads as a
            // deliberate marker and pokes through the ribbon.
            typeParams: { sizeFactor: 0.6, aromaticBonds: false },
            color: "uniform",
            colorParams: { value: Color(0x111827) },
          },
          // Tagged so addRepresentation updates the existing one instead of
          // appending another on every mutation change.
          { tag: "mutation-marker-repr" },
        );
      } catch (e) {
        // The marker is decoration; never break the viewer over it. Still
        // report it, because a silent failure here is indistinguishable from
        // the wildtype guard correctly declining to mark anything.
        console.warn("[marker] could not mark residue:", e);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [mutation, ready]);

  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="mb-3">
        <h3 className="text-sm font-medium">
          3D structure{" "}
          <span className="text-muted">· coloured by predicted impact</span>
        </h3>
        <p className="mt-0.5 text-xs text-muted">
          The folded shape, painted by how badly the model expects each position
          to break if changed. Red is intolerant, pale is relaxed. Drag to
          rotate; the red interior is the part that has to fold precisely.
          {mutation && (
            <>
              {" "}
              The dark residue is{" "}
              <span className="font-mono text-ink">{mutation}</span>.
            </>
          )}
        </p>
      </div>
      {error ? (
        <div className="text-sm text-muted">Could not load structure: {error}</div>
      ) : (
        // Mol* already fits the camera to the scene on first commit, so the
        // structure looking small was never a missing zoom. It fits the
        // SMALLER viewport dimension, and a full-width box here was ~1072x440
        // (aspect 2.44), so the protein filled the height but barely a third
        // of the width and the rest was empty canvas. Constraining the width
        // brings the frame near square and the structure fills it, with no
        // camera code at all. The heatmap and DSSP track keep full width.
        <div
          ref={parent}
          className="relative mx-auto w-full max-w-[640px] overflow-hidden rounded-md"
          style={{ height: 480 }}
        />
      )}
    </div>
  );
}
