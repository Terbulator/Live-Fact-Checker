import { motion } from 'framer-motion'
import { CheckCircle, XCircle, HelpCircle, MinusCircle, Shield } from 'lucide-react'

const verdicts = [
  {
    type: 'TRUE',
    label: 'The sources support the claim.',
    description:
      'Retrieved evidence backs the statement. When sources conflict or only one thin source matches, the verdict drops to AMBIGUOUS instead.',
    icon: CheckCircle,
    color: 'var(--supported)',
    colorSoft: 'var(--supported-soft)',
  },
  {
    type: 'FALSE',
    label: 'The sources contradict the claim.',
    description:
      'Retrieved evidence reports different figures, dates or facts that directly contradict what was said.',
    icon: XCircle,
    color: 'var(--refuted)',
    colorSoft: 'var(--refuted-soft)',
  },
  {
    type: 'UNVERIFIABLE',
    label: 'Not enough reliable evidence was found.',
    description:
      'No credible sources were retrieved, or what was retrieved is too weak to support any conclusion.',
    icon: HelpCircle,
    color: 'var(--unknown)',
    colorSoft: 'var(--unknown-soft)',
  },
  {
    type: 'AMBIGUOUS',
    label: 'The evidence supports more than one reading.',
    description:
      'Sources are in genuine conflict, or the claim depends on context that was never specified in the conversation.',
    icon: MinusCircle,
    color: '#b98cff',
    colorSoft: 'rgba(185, 140, 255, 0.14)',
  },
]

export function VerdictSystem() {
  return (
    <section className="verdict-system" id="verdicts" aria-labelledby="verdict-title">
      <div className="container">
        <motion.div
          className="section-header section-header--center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5 }}
        >
          <span className="section-eyebrow">VERDICT SYSTEM</span>
          <h2 id="verdict-title" className="section-title">
            Four verdicts. No fifth guess.
          </h2>
          <p className="section-description">
            Every claim ends in one of four states, with the evidence that decided it.
          </p>
        </motion.div>

        <div className="verdict-grid" role="list">
          {verdicts.map((verdict, index) => (
            <motion.article
              key={verdict.type}
              className="verdict-card"
              role="listitem"
              initial={{ opacity: 0, y: 30, scale: 0.98 }}
              whileInView={{ opacity: 1, y: 0, scale: 1 }}
              viewport={{ once: true, margin: '-100px' }}
              transition={{ duration: 0.5, delay: 0.1 + index * 0.1 }}
              style={
                {
                  '--verdict-color': verdict.color,
                  '--verdict-color-soft': verdict.colorSoft,
                } as React.CSSProperties
              }
            >
              <div className="verdict-card-icon">
                <verdict.icon size={28} strokeWidth={2} aria-hidden="true" />
              </div>
              <div className="verdict-card-type">{verdict.type}</div>
              <p className="verdict-card-label">{verdict.label}</p>
              <p className="verdict-card-description">{verdict.description}</p>
              <div className="verdict-card-principle">
                <Shield size={14} aria-hidden="true" />
                <span>Always evidence-backed</span>
              </div>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  )
}
