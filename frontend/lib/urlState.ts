"use client";

/**
 * Reading and writing the current prediction as URL parameters, so a result
 * can be linked to.
 *
 * Two deliberate choices:
 *
 * `window.location.search` rather than `useSearchParams()`. The route is
 * statically prerendered, and useSearchParams in a client component forces
 * dynamic rendering — the build fails outright unless the page is wrapped in
 * a Suspense boundary, and because everything on this page reads from one
 * prediction hook the boundary would have to swallow the whole page, trading
 * the prerendered HTML for a fallback.
 *
 * `history.replaceState` rather than `router.replace()`. The latter fetches an
 * RSC payload on every prediction and, by default, jerks the window back to
 * the top mid-result. replaceState also keeps the back button meaning "leave
 * the site" instead of stepping back through every query.
 */

export interface ShareParams {
  input: string;
  mutation: string;
}

// A URL is an untrusted, one-click way to make this app do work. Scoring an
// unseen protein wakes a scale-to-zero worker for minutes of CPU, so what a
// link may auto-run is deliberately narrow: recognisable identifiers only.
const MAX_INPUT = 64;
const MAX_MUTATION = 32;

// UniProt accession, PDB ID, or a gene-symbol-shaped token.
const SAFE_INPUT = /^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$/;
// Single or colon-joined substitutions, positions capped at four digits.
const SAFE_MUTATION = /^[A-Za-z]\d{1,4}[A-Za-z](:[A-Za-z]\d{1,4}[A-Za-z])*$/;

/**
 * Parse a shared link into something safe to run automatically.
 *
 * Returns `autoRun: false` when the protein is present but not something we
 * are willing to run unattended — a pasted sequence, most importantly. Those
 * still prefill the form so the visitor can press the button themselves; the
 * decision to spend the compute stays with a human.
 */
export function parseShareUrl(
  search: string,
): { params: ShareParams; autoRun: boolean } | null {
  const q = new URLSearchParams(search);
  const rawInput = (q.get("protein") ?? "").trim();
  if (!rawInput) return null;

  const rawMutation = (q.get("mutation") ?? "").trim().toUpperCase();
  const mutation =
    rawMutation.length <= MAX_MUTATION && SAFE_MUTATION.test(rawMutation)
      ? rawMutation
      : "";

  const safe = rawInput.length <= MAX_INPUT && SAFE_INPUT.test(rawInput);
  return {
    params: { input: rawInput.slice(0, MAX_INPUT), mutation },
    autoRun: safe,
  };
}

/** Reflect the current prediction in the address bar, without navigating. */
export function writeShareUrl({ input, mutation }: ShareParams): void {
  if (typeof window === "undefined") return;

  const url = new URL(window.location.href);
  const trimmed = input.trim();

  // Never put a pasted sequence in the URL. It would be unshareable anyway at
  // up to 1022 residues, and it would leak the sequence into browser history,
  // bookmarks and the Referer header sent to any link the page later opens.
  const shareable = trimmed.length <= MAX_INPUT && SAFE_INPUT.test(trimmed);

  if (shareable) {
    url.searchParams.set("protein", trimmed);
    if (mutation.trim()) {
      url.searchParams.set("mutation", mutation.trim().toUpperCase());
    } else {
      url.searchParams.delete("mutation");
    }
  } else {
    url.searchParams.delete("protein");
    url.searchParams.delete("mutation");
  }

  window.history.replaceState(null, "", url.toString());
}
