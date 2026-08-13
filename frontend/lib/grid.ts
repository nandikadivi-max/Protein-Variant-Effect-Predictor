/**
 * Geometry shared by every per-residue view.
 *
 * The effect map and the DSSP track are read together — "is the position the
 * heatmap is showing me buried?" — so they must use one grid. Both the cell
 * width and the left gutter have to match: equal cell widths keep the columns
 * the same size, and an equal gutter keeps column N at the same x in both,
 * which is what makes scrolling them in lockstep meaningful.
 */

/** Horizontal pixels per residue. */
export const CELL_W = 14;

/**
 * Width of the fixed label gutter to the left of the scrolling grid. Wide
 * enough for the track's "Buried" row label; the heatmap's single-letter
 * amino-acid axis simply right-aligns inside the same width.
 */
export const AXIS_W = 48;
