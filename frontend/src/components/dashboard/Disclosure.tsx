/**
 * A collapsible section of the result.
 *
 * Progressive disclosure, so it is a row and not a card: a label, what it holds,
 * and a chevron. The body appears inline underneath, which keeps the reader's
 * place in the conversation instead of moving them somewhere else.
 *
 * There is no icon here on purpose. Four rows each opening with their own glyph
 * reads as a dashboard's worth of furniture; a word and a number is quieter and
 * just as scannable.
 *
 * Real `<button aria-expanded>` with a labelled region, so the state is legible
 * to a screen reader and the row is reachable by keyboard.
 */

import { useId, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'

export interface DisclosureProps {
  label: string
  /** What the section holds, in the reader's terms: "7 claims checked". */
  meta: string | null
  /** The content. Not rendered until first opened. */
  children: ReactNode
  /** Rows the reader will most often want; opened by default. */
  defaultOpen?: boolean
  /** Show the row without its content, for a section with nothing in it yet. */
  disabled?: boolean
}

export function Disclosure({ label, meta, children, defaultOpen = false, disabled = false }: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen)
  const regionId = useId()

  return (
    <div className={`reveal${open ? ' reveal--open' : ''}`}>
      <button
        type="button"
        className="reveal__row"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={regionId}
        disabled={disabled}
      >
        <ChevronRight size={14} className="reveal__chevron" aria-hidden="true" />
        <span className="reveal__label">{label}</span>
        {meta !== null && <span className="reveal__meta">{meta}</span>}
      </button>

      <div id={regionId} className="reveal__body" role="region" aria-label={label} hidden={!open}>
        {open && children}
      </div>
    </div>
  )
}
