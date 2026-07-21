// A custom Mol* color theme that paints each residue by its predicted
// per-residue variant impact (mean ESM-2 LLR across substitutions). More
// negative = more mutation-intolerant = redder; ~0 = pale. Modeled on Mol*'s
// built-in sequence-id theme so it reads the same label_seq_id, which for an
// AlphaFold model equals the UniProt position (and thus the impact index).

import { Bond, StructureElement, Unit } from "molstar/lib/mol-model/structure";
import { Color } from "molstar/lib/mol-util/color";

const DefaultColor = Color(0xdddddd);

function getSeqId(unit: any, element: number): number {
  const { model } = unit;
  // Unit.isAtomic is a runtime guard (avoids the const-enum access that
  // isolatedModules forbids). Coarse-grained models aren't relevant here.
  if (Unit.isAtomic(unit)) {
    const residueIndex =
      model.atomicHierarchy.residueAtomSegments.index[element];
    return model.atomicHierarchy.residues.label_seq_id.value(residueIndex);
  }
  return -1;
}

export function makeImpactColorThemeProvider(impact: number[]) {
  const minImpact = Math.min(0, ...impact); // most damaging position (<= 0)

  function toColor(v: number): Color {
    const t = minImpact < 0 ? Math.min(1, Math.max(0, v / minImpact)) : 0;
    // pale (#F5F5F4) -> red (#B91C1C)
    const r = Math.round(245 + (185 - 245) * t);
    const g = Math.round(245 + (28 - 245) * t);
    const b = Math.round(244 + (28 - 244) * t);
    return Color.fromRgb(r, g, b);
  }

  function factory() {
    const color = (location: any): Color => {
      let seqId = -1;
      if (StructureElement.Location.is(location)) {
        seqId = getSeqId(location.unit, location.element);
      } else if (Bond.isLocation(location)) {
        seqId = getSeqId(location.aUnit, location.aUnit.elements[location.aIndex]);
      }
      if (seqId > 0 && seqId <= impact.length) return toColor(impact[seqId - 1]);
      return DefaultColor;
    };
    return {
      factory,
      granularity: "group" as const,
      preferSmoothing: true,
      color,
      props: {},
      description: "Per-residue predicted variant impact (ESM-2)",
    };
  }

  return {
    name: "variant-impact",
    label: "Variant impact",
    category: "Residue",
    factory,
    getParams: () => ({}),
    defaultValues: {},
    isApplicable: (ctx: any) => !!ctx.structure,
  };
}
