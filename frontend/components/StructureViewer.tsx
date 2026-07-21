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
      <h3 className="mb-3 text-sm font-medium">3D structure</h3>
      {error ? (
        <div className="text-sm text-muted">Could not load structure: {error}</div>
      ) : (
        <div
          ref={parent}
          className="relative overflow-hidden rounded-md"
          style={{ width: "100%", height: 440 }}
        />
      )}
    </div>
  );
}
