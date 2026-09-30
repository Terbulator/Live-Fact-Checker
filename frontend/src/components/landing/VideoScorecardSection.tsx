import { motion } from 'framer-motion'
import { Clock, User } from 'lucide-react'

import { SectionSurface, surfaceClass, VERDICTS } from './tone'

/**
 * Claim-level report preview.
 *
 * Rows are illustrative placeholders that show the *shape* of a real report:
 * timestamp, speaker, claim, verdict, confidence, supporting statement and
 * sources. The confidence column deliberately shows what happens when a provider
 * reports no score — N/A rather than a fabricated percentage.
 */

const ROWS = [
  {
    id: 'c1',
    time: '00:12',
    speaker: 'Speaker 1',
    claim: 'The venue for the final was in the coastal city.',
    verdict: 'TRUE',
    tone: 'true',
    confidence: 'Provider score',
    statement: 'Retrieved sources name the same city as the venue.',
    sources: ['Retrieved official source', 'Retrieved news source'],
  },
  {
    id: 'c2',
    time: '00:48',
    speaker: 'Speaker 1',
    claim: 'The monument shown is located in India.',
    verdict: 'FALSE',
    tone: 'false',
    confidence: 'N/A — no provider score',
    statement: 'Retrieved sources place it in a different country.',
    sources: ['Retrieved reference source'],
  },
  {
    id: 'c3',
    time: '01:26',
    speaker: 'Speaker 2',
    claim: 'Attendance was described only as a large number.',
    verdict: 'UNVERIFIABLE',
    tone: 'unverifiable',
    confidence: 'N/A — no provider score',
    statement: 'No retrieved source stated a figure.',
    sources: [],
  },
  {
    id: 'c4',
    time: '02:04',
    speaker: 'Speaker 2',
    claim: 'The figure was later revised upward.',
    verdict: 'AMBIGUOUS',
    tone: 'ambiguous',
    confidence: 'Provider score',
    statement: 'Retrieved sources disagree on whether a revision occurred.',
    sources: ['Retrieved news source', 'Retrieved dataset'],
  },
] as const

const TOTALS = { checked: 4, failed: 0 }

export function VideoScorecardSection({ surface = 'paper' }: { surface?: SectionSurface }) {
  return (
    <section id="report" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container">
        <span className="lfp-eyebrow">CLAIM BREAKDOWN</span>
        <h2 className="lfp-h2 lfp-h2--center">Claim by claim, with the reason attached.</h2>
        <p className="lfp-lede lfp-lede--center">
          A verdict is only useful if you can see what produced it.
        </p>

        <motion.div
          className="lfp-report"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.55, ease: [0.2, 0.7, 0.3, 1] }}
        >
          <div className="lfp-report__head">
            <p className="lfp-scorecard__title">Video report</p>
            <p className="lfp-scorecard__sub">
              {TOTALS.checked} claims checked · {TOTALS.failed} failed
            </p>
            <span className="lfp-window__tag">ILLUSTRATIVE PREVIEW</span>
          </div>

          <ul className="lfp-report__rows">
            {ROWS.map((row, index) => {
              return (
                <motion.li
                  key={row.id}
                  className={`lfp-report__row lfp-report__row--${row.tone}`}
                  initial={{ opacity: 0, y: 10 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: '-40px' }}
                  transition={{ duration: 0.4, delay: index * 0.1 }}
                >
                  <div className="lfp-report__meta">
                    <span>
                      <Clock size={13} aria-hidden="true" />
                      {row.time}
                    </span>
                    <span>
                      <User size={13} aria-hidden="true" />
                      {row.speaker}
                    </span>
                  </div>

                  <p className="lfp-report__claim">{row.claim}</p>

                  {/*
                    Colour alone never distinguishes an outcome, so each badge
                    also carries a distinct shape: ✓ ✕ ? ~
                  */}
                  <span
                    className={`lfp-verdict lfp-verdict--${row.tone} lfp-verdict--sm`}
                    role="img"
                    aria-label={`Verdict: ${row.verdict}`}
                  >
                    <span className="lfp-verdict__glyph" aria-hidden="true">
                      {VERDICTS[row.tone].glyph}
                    </span>
                    {row.verdict}
                  </span>

                  <p className="lfp-report__statement">{row.statement}</p>

                  <p className="lfp-report__confidence">
                    <span>CONFIDENCE</span>
                    <strong>{row.confidence}</strong>
                  </p>

                  {row.sources.length > 0 ? (
                    <ul className="lfp-report__sources">
                      {row.sources.map((source) => (
                        <li key={source}>{source}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="lfp-report__noSources">No source to cite</p>
                  )}
                </motion.li>
              )
            })}
          </ul>
        </motion.div>
      </div>
    </section>
  )
}
