import { motion } from 'framer-motion'
import { Mic, Search, Check, X, Clock, Brain } from 'lucide-react'

const oldWay = [
  { icon: Mic, label: 'Listen', desc: 'Try to hold the whole conversation in your head' },
  { icon: Clock, label: 'Pause', desc: 'Stop the discussion to deal with one claim' },
  { icon: Search, label: 'Search', desc: 'Manually search the web' },
  { icon: Brain, label: 'Read', desc: 'Read past the noise to find the real source' },
  { icon: X, label: 'Compare', desc: 'Decide yourself whether it holds up' },
]

const newWay = [
  { icon: Mic, label: 'LISTENS', desc: 'Continuous audio capture' },
  { icon: Brain, label: 'READS', desc: 'Claims extracted from speech' },
  { icon: Search, label: 'SEARCHES', desc: 'Live web evidence per claim' },
  { icon: Check, label: 'VERIFIES', desc: 'Verdict plus the sources' },
]

export function ProblemSolution() {
  return (
    <section className="problem-solution" id="problem" aria-labelledby="problem-title">
      <div className="container">
        <motion.div
          className="section-header"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5 }}
        >
          <span className="section-eyebrow">THE PROBLEM</span>
          <h2 id="problem-title" className="section-title">
            Fact-checking shouldn&apos;t have to wait.
          </h2>
          <p className="section-description">
            Live conversations move faster than manual verification. By the time you have
            paused, searched, read and compared, the moment has passed.
          </p>
        </motion.div>

        <div className="comparison">
          <motion.div
            className="comparison-column comparison-column--old"
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-100px' }}
            transition={{ duration: 0.5, delay: 0.1 }}
          >
            <div className="comparison-header">
              <span className="comparison-badge comparison-badge--old">MANUAL</span>
              <h3 className="comparison-title">The old way</h3>
            </div>
            <ol className="comparison-steps">
              {oldWay.map((step, index) => (
                <li key={step.label} className="comparison-step">
                  <div className="comparison-step-number">{index + 1}</div>
                  <div className="comparison-step-content">
                    <step.icon className="comparison-step-icon" aria-hidden="true" size={20} />
                    <div className="comparison-step-text">
                      <strong>{step.label}</strong>
                      <span>{step.desc}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
            <div className="comparison-summary">
              <span className="comparison-time">Interrupts the conversation</span>
            </div>
          </motion.div>

          <motion.div
            className="comparison-arrow"
            initial={{ opacity: 0, scale: 0.8 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true, margin: '-100px' }}
            transition={{ duration: 0.5, delay: 0.2 }}
            aria-hidden="true"
          >
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </motion.div>

          <motion.div
            className="comparison-column comparison-column--new"
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-100px' }}
            transition={{ duration: 0.5, delay: 0.25 }}
          >
            <div className="comparison-header">
              <span className="comparison-badge comparison-badge--new">LIVE FACT-CHECKER</span>
              <h3 className="comparison-title">The live way</h3>
            </div>
            <ol className="comparison-steps">
              {newWay.map((step, index) => (
                <li key={step.label} className="comparison-step">
                  <div className="comparison-step-number">{index + 1}</div>
                  <div className="comparison-step-content">
                    <step.icon className="comparison-step-icon" aria-hidden="true" size={20} />
                    <div className="comparison-step-text">
                      <strong>{step.label}</strong>
                      <span>{step.desc}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
            <div className="comparison-summary">
              <span className="comparison-time">The conversation keeps going</span>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  )
}
