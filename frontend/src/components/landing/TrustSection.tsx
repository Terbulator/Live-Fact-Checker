import { motion } from 'framer-motion'
import { Shield, Search, FileText, Eye, AlertTriangle, Globe } from 'lucide-react'

const trustPrinciples = [
  {
    icon: Shield,
    title: 'No invented citations',
    description:
      'Evidence comes from real search results with their URLs attached. Nothing is produced from a stored library of made-up facts.',
  },
  {
    icon: Search,
    title: 'The sources are the answer',
    description:
      'Each verdict ships with the snippets that produced it, so you can open the source and read it yourself.',
  },
  {
    icon: FileText,
    title: 'The reasoning is shown',
    description:
      'The claim card carries the verdict and the evidence behind it rather than a bare label.',
  },
  {
    icon: AlertTriangle,
    title: 'UNVERIFIABLE means unverified',
    description:
      'Missing, weak or conflicting evidence returns UNVERIFIABLE or AMBIGUOUS. Those are real outcomes, not failures to hide.',
  },
  {
    icon: Globe,
    title: 'Current, not cached facts',
    description:
      'Claims are checked against a live web search, so the evidence reflects what is published now.',
  },
  {
    icon: Eye,
    title: 'It only observes',
    description:
      'The frontend starts sessions and renders what the backend streams. It never produces a transcript, claim or verdict of its own.',
  },
]

export function TrustSection() {
  return (
    <section className="trust-section" id="trust" aria-labelledby="trust-title">
      <div className="container">
        <motion.div
          className="section-header section-header--center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5 }}
        >
          <span className="section-eyebrow">TRUST</span>
          <h2 id="trust-title" className="section-title">
            Evidence first. Guessing never.
          </h2>
          <p className="section-description">
            No accuracy claims. What the system can promise is that you will be able to see
            exactly where each verdict came from.
          </p>
        </motion.div>

        <div className="trust-grid" role="list">
          {trustPrinciples.map((principle, index) => (
            <motion.article
              key={principle.title}
              className="trust-card"
              role="listitem"
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-100px' }}
              transition={{ duration: 0.5, delay: 0.1 + index * 0.08 }}
            >
              <div className="trust-card-icon">
                <principle.icon size={24} strokeWidth={1.8} aria-hidden="true" />
              </div>
              <h3 className="trust-card-title">{principle.title}</h3>
              <p className="trust-card-description">{principle.description}</p>
            </motion.article>
          ))}
        </div>

        <motion.div
          className="trust-principle"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5, delay: 0.5 }}
        >
          <div className="trust-principle-content">
            <Shield className="trust-principle-icon" size={28} aria-hidden="true" />
            <div className="trust-principle-text">
              <strong>No claim here is faster than the evidence behind it.</strong>
              <p>
                Verdicts appear as the pipeline resolves them, and each one is labelled with
                what it rests on. If nothing settled the claim, you will see that too.
              </p>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
