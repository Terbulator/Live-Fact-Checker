/**
 * Colour system for the marketing page.
 *
 * Colours are named by *role*, not by hue, and every one of them is a CSS
 * custom property declared on `.lfp-root`. Components reference roles
 * (`surface`, `accent`) and never a hex value, so a palette change is a
 * stylesheet edit.
 *
 * Five visual layers, each a step removed from the last:
 *
 *   base      the page ground
 *   surface   a section ground, one step off the base
 *   card      a raised panel inside a section
 *   highlight a tinted card that carries meaning
 *   accent    a small area: a border, icon, badge or rule
 *
 * Accent families exist for grouping, never decoration. A card picks one so
 * the eye can group related items at a glance, and the tint is weak enough that
 * the page still reads as editorial rather than as a swatch book.
 */

/** A section ground. Sections must not repeat a surface back to back. */
export type SectionSurface =
  | 'paper' // warm off-white
  | 'white' // pure white
  | 'warm' // warm white
  | 'beige' // soft beige
  | 'mint' // very light green tint
  | 'charcoal' // dark charcoal
  | 'black' // deep black
  | 'night' // near-black, slightly lifted

/** Accent families. Each has a muted tone for text/borders and a soft tint. */
export type AccentKey =
  | 'green'
  | 'blue'
  | 'yellow'
  | 'orange'
  | 'lavender'
  | 'red'

/** True when a surface is dark enough to need light type. */
export const isDarkSurface = (surface: SectionSurface): boolean =>
  surface === 'charcoal' || surface === 'black' || surface === 'night'

export const surfaceClass = (surface: SectionSurface): string => `lfp-bg--${surface}`

/** Modifier for a card or node that carries an accent identity. */
export const accentClass = (accent?: AccentKey): string =>
  accent ? `lfp-accent--${accent}` : ''

/**
 * Verdict presentation.
 *
 * Keyed lowercase so it lines up with the `tone` field used across the
 * components. `glyph` is deliberate: colour alone never distinguishes the
 * outcomes, so each verdict also carries a distinct shape (check, cross,
 * question, tilde).
 */
export const VERDICTS = {
  true: { label: 'TRUE', glyph: '✓', accent: 'green' as AccentKey },
  false: { label: 'FALSE', glyph: '✕', accent: 'red' as AccentKey },
  unverifiable: { label: 'UNVERIFIABLE', glyph: '?', accent: 'yellow' as AccentKey },
  ambiguous: { label: 'AMBIGUOUS', glyph: '~', accent: 'lavender' as AccentKey },
} as const

export type VerdictKey = keyof typeof VERDICTS

/** Map a backend verdict string onto its key, e.g. "UNVERIFIABLE" -> "unverifiable". */
export const verdictKey = (verdict: string): VerdictKey =>
  verdict.trim().toLowerCase() as VerdictKey
