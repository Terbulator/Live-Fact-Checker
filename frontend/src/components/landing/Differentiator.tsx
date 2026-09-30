import { motion } from 'framer-motion'
import { Database, Zap, Globe, Brain, Shield, ArrowRight } from 'lucide-react'

const differentiators = [
  {
    icon: Database,
    title: 'No preloaded fact database',
    description:
      'There is no fixed library of stored facts to look a claim up in. Each claim is investigated fresh, at the moment it is made.',
  },
  {
    icon: Zap,
    title: 'Claims found, not predefined',
    description:
      'The claim extractor reads the transcript itself. There is no list of topics it was built to look for.',
  },
  {
    icon: Globe,
    title: 'Searches the current web',
    description:
      'Evidence comes from a live search, so it reflects what is published now rather than a snapshot taken earlier.',
  },
  {
    icon: Brain,
    title: 'Evidence decides the verdict',
    description:
      'The verdict is computed from the retrieved snippets. When they are thin, the result is weak rather than confident.',
  },
  {
    icon: Shield,
    title: 'Says so when it cannot tell',
    description:
      'Missing or conflicting evidence produces UNVERIFIABLE or AMBIGUOUS, not a guess dressed up as a finding.',
  },
]

const flow = ['Speech', 'Extracted claim', 'Live search', 'Retrieved evidence', 'Verdict + sources']

export function Differentiator() {
  return (
    <section className="differentiator" id="how-it-differs" aria-labelledby="diff-title">
      <div className="container">
        <motion.div
          className="section-header section-header--center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5 }}
        >
          <span className="section-eyebrow">WHAT MAKES IT DIFFERENT</span>
          <h2 id="diff-title" className="section-title section-title--large">
            Not a fact database with a microphone attached.
          </h2>
          <p className="section-description section-description--large">
            It investigates the claim being made <strong>right now</strong>.
          </p>
        </motion.div>

        <motion.div
          className="diff-flow"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5, delay: 0.1 }}
        >
          {flow.map((label, index) => (
            <div key={label} className="diff-flow-node">
              <div className="diff-flow-step">
                <span className="diff-flow-label">{label}</span>
              </div>
              {index < flow.length - 1 && (
                <ArrowRight className="diff-flow-arrow" size={22} aria-hidden="true" />
              )}
            </div>
          ))}
        </motion.div>

        <motion.div
          className="differentiators-grid"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5, delay: 0.2 }}
          role="list"
        >
          {differentiators.map((item, index) => (
            <motion.article
              key={item.title}
              className="diff-card"
              role="listitem"
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: 0.3 + index * 0.08 }}
            >
              <div className="diff-card-icon">
                <item.icon size={24} strokeWidth={1.8} aria-hidden="true" />
              </div>
              <h3 className="diff-card-title">{item.title}</h3>
              <p className="diff-card-description">{item.description}</p>
            </motion.article>
          ))}
        </motion.div>
      </div>
    </section>
  )
}
