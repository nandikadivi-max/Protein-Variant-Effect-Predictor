// A custom Mol* color theme that paints each residue by its predicted
// per-residue variant impact (mean ESM-2 LLR across substitutions). More
// negative = more mutation-intolerant = redder; ~0 = pale.
//
// Numbering is the whole difficulty here. The impact array is indexed by
// UniProt position, but a structure file is numbered however its depositors
// numbered it. This originally read label_seq_id, which happens to equal the
// UniProt position for an AlphaFold model and is badly wrong for a cropped
// experimental one: in 1TUP the p53 DNA-binding domain runs 1-219 by
// label_seq_id but 94-312 in UniProt, so every residue was painted with the
// impact of a residue 93 positions away.
//
// So residues are located by author numbering and mapped through the SIFTS
// segments the backend already stores — the same mapping worker/features/dssp
// applies when projecting structural features onto UniProt coordinates.
// AlphaFold models pass no segments and fall through to identity, which is
// correct for them.

import { Bond, StructureElement, Unit } from "molstar/lib/mol-model/structure";
import { Color } from "molstar/lib/mol-util/color";

const DefaultColor = Color(0xdddddd);
// Residues the structure covers but the mapping doesn't place in the sequence.
const UnmappedColor = Color(0xe8e6e3);

export interface SiftsSegment {
  chain_id: string;
  pdb_start: number;
  pdb_end: number;
  unp_start: number;
  unp_end: number;
}

/** Author residue number + chain -> 1-based UniProt position, or -1. */
function toUniProtPosition(
  chainId: string,
  authSeqId: number,
  segments: SiftsSegment[],
): number {
  if (segments.length === 0) return authSeqId; // AlphaFold: already UniProt
  for (const seg of segments) {
    if (seg.chain_id !== chainId) continue;
    if (authSeqId >= seg.pdb_start && authSeqId <= seg.pdb_end) {
      return authSeqId + (seg.unp_start - seg.pdb_start);
    }
  }
  return -1;
}

function locate(unit: any, element: number): { chainId: string; authSeqId: number } | null {
  const { model } = unit;
  // Unit.isAtomic is a runtime guard (avoids the const-enum access that
  // isolatedModules forbids). Coarse-grained models aren't relevant here.
  if (!Unit.isAtomic(unit)) return null;
  const h = model.atomicHierarchy;
  const residueIndex = h.residueAtomSegments.index[element];
  const chainIndex = h.chainAtomSegments.index[element];
  return {
    chainId: h.chains.auth_asym_id.value(chainIndex),
    authSeqId: h.residues.auth_seq_id.value(residueIndex),
  };
}

export function makeImpactColorThemeProvider(
  impact: number[],
  segments: SiftsSegment[] = [],
) {
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
      let found: { chainId: string; authSeqId: number } | null = null;
      if (StructureElement.Location.is(location)) {
        found = locate(location.unit, location.element);
      } else if (Bond.isLocation(location)) {
        found = locate(
          location.aUnit,
          location.aUnit.elements[location.aIndex],
        );
      }
      if (!found) return DefaultColor;

      const pos = toUniProtPosition(found.chainId, found.authSeqId, segments);
      if (pos > 0 && pos <= impact.length) return toColor(impact[pos - 1]);
      // Covered by the structure but not placed in the sequence: a ligand, a
      // nucleic acid chain, a tag. Better neutral than a wrong impact colour.
      return UnmappedColor;
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
