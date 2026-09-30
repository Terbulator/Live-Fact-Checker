import { useState } from 'react'
import { motion } from 'framer-motion'

import { SectionSurface, accentClass, surfaceClass } from './tone'

/**
 * Interactive evidence flow.
 *
 * Each node explains itself on hover and on focus, so the sequence is legible
 * without a pointer. The content describes the mechanism; it carries no
 * citations and no results.
 */

const NODES = [
  {
    id: 'claim',
    label: 'CLAIM',
    note: 'A finalized transcript line that can actually be checked.',
  },
  {
    id: 'extract',
    label: 'EXTRACT',
    note: 'The claim text is isolated verbatim. Numbers, dates and names are preserved exactly as spoken.',
  },
  {
    id: 'search',
    label: 'SEARCH',
    note: 'A query is generated from the claim and sent to a live web search provider.',
  },
  {
    id: 'evidence',
    label: 'EVIDENCE',
    note: 'Retrieved snippets are kept only when they carry a real, citable URL.',
  },
  {
    id: 'verify',
    label: 'VERIFY',
    note: 'The evidence is compared against the claim. A failed search produces no verdict.',
  },
  {
    id: 'verdict',
    label: 'VERDICT',
    note: 'TRUE, FALSE, UNVERIFIABLE or AMBIGUOUS — with the sources that produced it.',
  },
]

export function EvidenceFlow({ surface = 'paper' }: { surface?: SectionSurface }) {
  const [active, setActive] = useState<string | null>(null)

  return (
    <section id="evidence" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container">
        <span className="lfp-eyebrow">EVIDENCE</span>
        <h2 className="lfp-h2 lfp-h2--center">Every claim gets its own evidence.</h2>
        <p className="lfp-lede lfp-lede--center">
          The verdict is a consequence of retrieval. If retrieval finds nothing, the
          answer is UNVERIFIABLE — not a guess.
        </p>

        <ol className="lfp-flow" onMouseLeave={() => setActive(null)}>
          {NODES.map((node, index) => {
            const isActive = active === node.id
            return (
              <li key={node.id} className="lfp-flow__item">
                <motion.button
                  type="button"
                  className={`lfp-flow__node${isActive ? ' lfp-flow__node--active' : ''}`}
                  onMouseEnter={() => setActive(node.id)}
                  onFocus={() => setActive(node.id)}
                  onClick={() => setActive(isActive ? null : node.id)}
                  aria-expanded={isActive}
                  initial={{ opacity: 0, y: 14 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: '-60px' }}
                  transition={{ duration: 0.4, delay: index * 0.08 }}
                >
                  <span className="lfp-flow__index">{String(index + 1).padStart(2, '0')}</span>
                  <span className="lfp-flow__label">{node.label}</span>
                </motion.button>

                {index < NODES.length - 1 ? (
                  <span className="lfp-flow__arrow" aria-hidden="true">
                    <motion.i
                      initial={{ scaleX: 0 }}
                      whileInView={{ scaleX: 1 }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.5, delay: 0.2 + index * 0.08 }}
                    />
                  </span>
                ) : null}

                <motion.p
                  className="lfp-flow__note"
                  initial={false}
                  animate={{
                    opacity: isActive ? 1 : 0,
                    y: isActive ? 0 : -4,
                  }}
                  transition={{ duration: 0.22 }}
                  aria-live="polite"
                >
                  {isActive ? node.note : ''}
                </motion.p>
              </li>
            )
          })}
        </ol>
      </div>
    </section>
  )
}

const SOURCE_KINDS = [
  {
    title: 'Official source',
    body: 'Governments, regulators and sporting bodies publishing the primary record.',
    accent: 'green',
  },
  {
    title: 'News source',
    body: 'Reporting that cites where a figure or event came from.',
    accent: 'blue',
  },
  {
    title: 'Reference source',
    body: 'Encyclopaedic and archival material for context.',
    accent: 'lavender',
  },
  {
    title: 'Dataset',
    body: 'Structured data published for machine consumption.',
    accent: 'yellow',
  },
  {
    title: 'Government source',
    body: 'Statistical agencies and public filings.',
    accent: 'orange',
  },
] as const

/**
 * Generic source *categories*, deliberately not real citations. The product
 * shows whatever the search actually returned; this section only explains the
 * kinds of source that can appear.
 */
export function SourcesSection({ surface = 'warm' }: { surface?: SectionSurface }) {
  return (
    <section id="sources" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container">
        <span className="lfp-eyebrow">SOURCES</span>
        <h2 className="lfp-h2 lfp-h2--center">Live Fact Checker connects each verdict to retrieved evidence.</h2>
        <p className="lfp-lede lfp-lede--center">
          Nothing is asserted from memory. If a source cannot be retrieved and cited, it
          is not shown.
        </p>

        <div className="lfp-sources">
          {SOURCE_KINDS.map((kind, index) => (
            <motion.article
              key={kind.title}
              className={`lfp-sources__card ${accentClass(kind.accent)}`}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.45, delay: index * 0.07 }}
            >
              <span className="lfp-sources__icon" aria-hidden="true" />
              <h3 className="lfp-card__title">{kind.title}</h3>
              <p className="lfp-card__body">{kind.body}</p>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  )
}
