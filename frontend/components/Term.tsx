"use client";

import { TERMS } from "@/lib/glossary";

/**
 * A domain word with its definition one hover (or long-press) away.
 *
 * Deliberately not a click-to-open popover: the definitions are short enough
 * that a native title tooltip carries them, and a reader who already knows the
 * word should not have the layout shift under them.
 */
export function Term({
  k,
  children,
}: {
  k: keyof typeof TERMS | string;
  children?: React.ReactNode;
}) {
  const definition = TERMS[k];
  if (!definition) return <>{children ?? k}</>;
  return (
    <abbr
      title={definition}
      className="cursor-help border-b border-dotted border-muted/50 no-underline decoration-0"
    >
      {children ?? k}
    </abbr>
  );
}
