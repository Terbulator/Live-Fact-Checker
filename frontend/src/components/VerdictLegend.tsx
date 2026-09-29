/**
 * Legend explaining the three verdicts.
 *
 * Present because `UNVERIFIABLE` is the most misread verdict in the product: it
 * is not a soft "true", it means the evidence was missing, weak or conflicting.
 */

import { VERDICTS } from '../types/events'
import { describeVerdict } from '../lib/verdicts'

export function VerdictLegend() {
  return (
    <section className="panel" aria-label="Verdict legend">
      <h2 className="panel__title">What the verdicts mean</h2>
      <dl className="legend">
        {VERDICTS.map((verdict) => {
          const descriptor = describeVerdict(verdict)
          return (
            <div className="legend__item" key={verdict}>
              <dt>
                <span className={`verdict verdict--${descriptor.tone}`}>
                  {descriptor.short}
                </span>
              </dt>
              <dd>{descriptor.description}</dd>
            </div>
          )
        })}
      </dl>
    </section>
  )
}
