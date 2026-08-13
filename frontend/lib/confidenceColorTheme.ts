// Colour an AlphaFold model by its own confidence (pLDDT).
//
// Why this exists: a predicted model shown as solid cartoon reads as if it
// were structure. For TP53 nearly a third of atoms sit below pLDDT 50 — the
// band AlphaFold itself describes as "should not be interpreted", typically
// disordered — and we were painting all of it with mutational impact and
// captioning it "the folded shape". Showing a prediction without its
// confidence is the standard criticism of AlphaFold figures, and the data was
// already in the file we download.
//
// Bands and colours are AlphaFold's own, so anyone who has used the EBI viewer
// reads them without a legend.
//
// This theme is ONLY valid for predicted models. In an experimental structure
// the same B-factor column holds the atomic displacement parameter, where high
// means *mobile* rather than *confident* — the exact inverse. The viewer only
// offers this mode when the provider is AlphaFold.

import { Bond, StructureElement, Unit } from "molstar/lib/mol-model/structure";
import { Color } from "molstar/lib/mol-util/color";

const VERY_HIGH = Color(0x0053d6); // pLDDT > 90
const CONFIDENT = Color(0x65cbf3); // 70-90
const LOW = Color(0xffdb13); // 50-70
const VERY_LOW = Color(0xff7d45); // < 50
const UNKNOWN = Color(0xdddddd);

export const PLDDT_BANDS = [
  { label: "Very high", detail: "pLDDT > 90", color: "#0053D6" },
  { label: "Confident", detail: "70–90", color: "#65CBF3" },
  { label: "Low", detail: "50–70", color: "#FFDB13" },
  { label: "Very low", detail: "< 50", color: "#FF7D45" },
];

function bandFor(plddt: number): Color {
  if (plddt > 90) return VERY_HIGH;
  if (plddt > 70) return CONFIDENT;
  if (plddt > 50) return LOW;
  return VERY_LOW;
}

function readPlddt(unit: any, element: number): number | null {
  if (!Unit.isAtomic(unit)) return null;
  // AlphaFold writes per-residue pLDDT into the B-factor column, so every
  // atom of a residue carries the same value.
  const b = unit.model?.atomicConformation?.B_iso_or_equiv;
  if (!b) return null;
  const value = b.value(element);
  return Number.isFinite(value) ? value : null;
}

export function makeConfidenceColorThemeProvider() {
  function factory() {
    const color = (location: any): Color => {
      let plddt: number | null = null;
      if (StructureElement.Location.is(location)) {
        plddt = readPlddt(location.unit, location.element);
      } else if (Bond.isLocation(location)) {
        plddt = readPlddt(
          location.aUnit,
          location.aUnit.elements[location.aIndex],
        );
      }
      return plddt === null ? UNKNOWN : bandFor(plddt);
    };
    return {
      factory,
      granularity: "group" as const,
      preferSmoothing: true,
      color,
      props: {},
      description: "AlphaFold model confidence (pLDDT)",
    };
  }

  return {
    name: "plddt-confidence",
    label: "Model confidence",
    category: "Validation",
    factory,
    getParams: () => ({}),
    defaultValues: {},
    isApplicable: (ctx: any) => !!ctx.structure,
  };
}
