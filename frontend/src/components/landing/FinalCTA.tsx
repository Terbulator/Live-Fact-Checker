import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, Mic, FileText } from 'lucide-react'

export function FinalCTA() {
  return (
    <section className="final-cta" id="start" aria-labelledby="cta-title">
      <div className="container">
        <motion.div
          className="final-cta-content"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.6 }}
        >
          <h2 id="cta-title" className="final-cta-title">
            Start checking claims
            <br />
            <span className="final-cta-highlight">while they are still being said.</span>
          </h2>

          <p className="final-cta-subtitle">
            The fact-checker runs now. Accounts and stored history are not built yet.
          </p>

          <div className="final-cta-buttons">
            <Link to="/dashboard" className="button button--primary button--lg final-cta-primary">
              <span>Open the fact-checker</span>
              <ArrowRight className="final-cta-arrow" aria-hidden="true" />
            </Link>
            <a href="/#roadmap" className="button button--secondary button--lg final-cta-secondary">
              <span>See what&apos;s coming</span>
            </a>
          </div>

          <div className="final-cta-features">
            <div className="final-cta-feature">
              <Mic className="final-cta-feature-icon" size={18} aria-hidden="true" />
              <span>Live microphone input</span>
            </div>
            <div className="final-cta-feature">
              <FileText className="final-cta-feature-icon" size={18} aria-hidden="true" />
              <span>Source-backed evidence</span>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
