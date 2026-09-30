import { motion } from 'framer-motion'
import { Mic, Brain, Globe, FileText, CheckCircle, Database } from 'lucide-react'

const pipeline = [
  { icon: Mic, label: 'Transcription', desc: 'AssemblyAI', detail: 'Streaming speech to text over WebSocket' },
  { icon: Brain, label: 'Claim extraction', desc: 'LLM gateway', detail: 'Structured claims from recent transcript' },
  { icon: Globe, label: 'Web search', desc: 'Tavily', detail: 'Live query per claim' },
  { icon: FileText, label: 'Evidence', desc: 'Retriever', detail: 'Snippets, URLs, relevance' },
  { icon: CheckCircle, label: 'Verification', desc: 'Engine', detail: 'Stance and numeric comparison' },
  { icon: Database, label: 'Persistence', desc: 'Supabase', detail: 'Session records and verdict cache' },
]

export function Technology() {
  return (
    <section className="technology" id="technology" aria-labelledby="tech-title">
      <div className="container">
        <motion.div
          className="section-header section-header--center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5 }}
        >
          <span className="section-eyebrow">TECHNOLOGY</span>
          <h2 id="tech-title" className="section-title">
            Built as a real-time pipeline.
          </h2>
          <p className="section-description">
            Six components, each responsible for one job. The browser only renders what the
            backend streams to it.
          </p>
        </motion.div>

        <motion.div
          className="tech-pipeline"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5, delay: 0.1 }}
        >
          {pipeline.map((step, index) => (
            <motion.div
              key={step.label}
              className="tech-pipeline-step"
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: 0.1 + index * 0.07 }}
            >
              <div className="tech-pipeline-icon">
                <step.icon size={22} strokeWidth={1.8} aria-hidden="true" />
              </div>
              <div className="tech-pipeline-label">{step.label}</div>
              <div className="tech-pipeline-desc">{step.desc}</div>
              <p className="tech-pipeline-detail">{step.detail}</p>
            </motion.div>
          ))}
        </motion.div>

        <motion.div
          className="tech-notes"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5, delay: 0.3 }}
        >
          <article className="tech-note">
            <h3 className="tech-note-title">Mock engines for local runs</h3>
            <p className="tech-note-desc">
              The backend has a deterministic mock mode, so the full pipeline can be exercised
              without any API keys. Production credentials are read from the environment on the
              server and never reach the browser.
            </p>
          </article>
          <article className="tech-note">
            <h3 className="tech-note-title">Optional Supabase persistence</h3>
            <p className="tech-note-desc">
              When a database URL is configured, sessions and verdicts are written and a
              verdict cache is consulted. When it is not configured, persistence is disabled
              and the live pipeline is unaffected.
            </p>
          </article>
        </motion.div>
      </div>
    </section>
  )
}
