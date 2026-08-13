"use client";

import { useEffect, useRef, useState } from "react";
import "molstar/build/viewer/molstar.css";
import { makeImpactColorThemeProvider } from "@/lib/impactColorTheme";

interface Props {
  fileUrl: string;
  perResidueImpact: number[];
}

// A minimal embedded Mol* viewer. Loads the PDB served by the backend and
// shows a cartoon. Per-residue impact coloring is layered on in a follow-up.
export function StructureViewer({ fileUrl, perResidueImpact }: Props) {
  const parent = useRef<HTMLDivElement>(null);
  const pluginRef = useRef<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;

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
        const provider = makeImpactColorThemeProvider(perResidueImpact);
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
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      }
    })();

    return () => {
      disposed = true;
      pluginRef.current?.dispose?.();
      pluginRef.current = null;
    };
  }, [fileUrl, perResidueImpact]);

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
