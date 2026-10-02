/**
 * A collapsed disclosure for machine output.
 *
 * Raw backend codes, provider messages and stack-shaped strings are useful when
 * something is broken and noise in every other moment. This keeps them one click
 * away without ever putting them in front of a reader who only needs to know
 * that something failed.
 *
 * Deliberately a native `<details>`: it is keyboard accessible and works
 * without JavaScript, and it adds no state to any parent.
 */

import type { ReactNode } from 'react'

export interface TechnicalDetailsProps {
  /** Label for the collapsed row. */
  summary?: string
  children: ReactNode
}

export function TechnicalDetails({ summary = 'Technical details', children }: TechnicalDetailsProps) {
  return (
    <details className="tech">
      <summary className="tech__summary">{summary}</summary>
      <div className="tech__body">
        <pre className="tech__pre">{children}</pre>
      </div>
    </details>
  )
}