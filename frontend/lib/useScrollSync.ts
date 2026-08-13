"use client";

import { useEffect, type RefObject } from "react";

/**
 * Keep several horizontally-scrolling panes locked to the same offset.
 *
 * The effect map and the DSSP track are drawn on the same 14px-per-residue
 * grid so that a column in one lines up with the same residue in the other —
 * but they live in separate scroll containers, so that alignment silently
 * broke the moment either one moved. In particular the heatmap auto-scrolls
 * to centre a queried mutation, which left the track showing the N-terminus
 * while the heatmap showed position 175. Anyone trying to check whether the
 * mutated residue is buried was reading the wrong part of the protein.
 *
 * Panes register by group name and mirror each other on scroll. A late-mounting
 * pane (the track reveals after the heatmap, on a Framer Motion delay) adopts
 * the group's current offset when it joins.
 */
const GROUPS = new Map<string, Set<HTMLElement>>();

// Sub-pixel and clamping differences between panes of unequal width would
// otherwise ping-pong forever; ignore anything under a pixel.
const EPSILON = 1;

export function useScrollSync(
  group: string,
  ref: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let peers = GROUPS.get(group);
    if (!peers) {
      peers = new Set();
      GROUPS.set(group, peers);
    }
    const set = peers;

    // Adopt the current offset when joining an already-scrolled group. Deferred
    // a frame because a pane revealing behind an animation has no width yet,
    // and assigning scrollLeft to a zero-width element is a no-op.
    if (set.size > 0) {
      const [leader] = set;
      const offset = leader.scrollLeft;
      requestAnimationFrame(() => {
        if (Math.abs(el.scrollLeft - offset) > EPSILON) el.scrollLeft = offset;
      });
    }
    set.add(el);

    const onScroll = () => {
      // No re-entrancy guard needed: assigning only when the peer actually
      // differs means the echoed scroll event finds nothing left to do.
      for (const peer of set) {
        if (peer !== el && Math.abs(peer.scrollLeft - el.scrollLeft) > EPSILON) {
          peer.scrollLeft = el.scrollLeft;
        }
      }
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      set.delete(el);
      if (set.size === 0) GROUPS.delete(group);
    };
  }, [group, ref]);
}
