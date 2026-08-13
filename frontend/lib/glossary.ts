// Plain-English glossary. The app is aimed at two audiences that share almost
// no vocabulary: people who know proteins but not language models, and people
// who know language models but not proteins. Every domain term that appears in
// the UI gets a one-line definition here so neither group has to guess.

export const AA_NAMES: Record<string, string> = {
  A: "alanine",
  C: "cysteine",
  D: "aspartic acid",
  E: "glutamic acid",
  F: "phenylalanine",
  G: "glycine",
  H: "histidine",
  I: "isoleucine",
  K: "lysine",
  L: "leucine",
  M: "methionine",
  N: "asparagine",
  P: "proline",
  Q: "glutamine",
  R: "arginine",
  S: "serine",
  T: "threonine",
  V: "valine",
  W: "tryptophan",
  Y: "tyrosine",
};

export const TERMS: Record<string, string> = {
  protein:
    "A chain of amino acids that folds into a 3D shape. The shape determines what it does.",
  "amino acid":
    "The building blocks of proteins. There are 20 of them, each written as one letter, so a protein is a string over a 20-letter alphabet.",
  residue:
    "One amino acid at one position in the chain. Position 175 holds one residue.",
  mutation:
    "A change to the sequence. Here: swapping one amino acid for another at one position.",
  missense:
    "A mutation that swaps one amino acid for a different one (rather than truncating the protein). That is the only kind this tool scores.",
  "wild type":
    "The normal, unmutated version of the sequence. It's the reference you compare against.",
  "zero-shot":
    "The model was never trained on mutation outcomes. It only learned which sequences look plausible, and the score falls out of that.",
  llr:
    "Log-likelihood ratio: log P(mutant) − log P(wild type) at the mutated position. Negative means the model finds the substitute less plausible than the original.",
  "effect map":
    "Every possible single substitution, meaning all 20 amino acids at every position, scored at once.",
  percentile:
    "Where this mutation's score falls among all 19 alternatives at every position in this protein. It's a ranking within one protein, not a probability that the mutation is harmful.",
  "secondary structure":
    "Local shapes the chain folds into: helices (coils), strands (flat sheets), or neither (loops).",
  buried:
    "The residue is packed inside the folded protein rather than on the surface. Buried positions tend to tolerate change poorly.",
  dssp:
    "The standard algorithm for reading secondary structure and solvent exposure out of a 3D structure.",
  uniprot:
    "The reference database of protein sequences. P04637 is UniProt's ID for human TP53.",
  pdb: "The database of experimentally determined 3D protein structures.",
  fasta:
    "A plain-text format for a sequence: a header line, then the amino acid letters.",
  alphafold:
    "DeepMind's database of predicted 3D structures, covering proteins nobody has solved experimentally.",
  clinvar:
    "A public archive of human genetic variants and their clinical interpretations.",
};

/** "R175H" -> "arginine → histidine at position 175". Null if not a simple substitution. */
export function describeMutation(mutation: string): string | null {
  const m = /^([A-Z])(\d+)([A-Z])$/.exec(mutation.trim());
  if (!m) return null;
  const [, wt, pos, mut] = m;
  const from = AA_NAMES[wt];
  const to = AA_NAMES[mut];
  if (!from || !to) return null;
  return `${from} → ${to} at position ${pos}`;
}
