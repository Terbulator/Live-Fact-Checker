import { motion } from 'framer-motion'
import { Check } from 'lucide-react'

const available = [
  { title: 'Live microphone sessions', desc: 'Stream microphone audio and fact-check it as the conversation happens' },
  { title: 'Streaming transcription', desc: 'Interim and final transcript segments as they are produced' },
  { title: 'Claim extraction', desc: 'An LLM separates checkable assertions from opinion in the transcript' },
  { title: 'Live web evidence', desc: 'Each claim is searched against current web sources' },
  { title: 'Source-backed verdicts', desc: 'TRUE / FALSE / UNVERIFIABLE / AMBIGUOUS with the sources attached' },
  { title: 'Deterministic demo mode', desc: 'Run the whole pipeline with no API keys to see how it behaves' },
]

const next = [
  { title: 'File and video uploads', desc: 'Check a recorded conversation, lecture or interview' },
  { title: 'Call and meeting capture', desc: 'Check a phone or video call while it is happening' },
  { title: 'Per-speaker attribution', desc: 'Attribute each claim to the person who said it' },
]

const later = [
  { title: 'Video URL analysis', desc: 'Paste a public video URL and check its spoken claims' },
  { title: 'Browser extension', desc: 'Check claims while reading on the web' },
  { title: 'Team workspaces', desc: 'Share sessions and verdicts across a team' },
]

export function Roadmap() {
  return (
    <section className="roadmap" id="roadmap" aria-labelledby="roadmap-title">
      <div className="container">
        <motion.div
          className="section-header section-header--center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5 }}
        >
          <span className="section-eyebrow">ROADMAP</span>
          <h2 id="roadmap-title" className="section-title">
            What exists, and what does not.
          </h2>
          <p className="section-description">
            Only the first column is built. Everything else is listed as coming soon rather
            than implied to be available.
          </p>
        </motion.div>

        <div className="roadmap-grid" role="list">
          <motion.div
            className="roadmap-column roadmap-column--available"
            role="listitem"
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-100px' }}
            transition={{ duration: 0.5 }}
          >
            <div className="roadmap-column-head">
              <span className="roadmap-column-label">AVAILABLE NOW</span>
              <span className="roadmap-column-title">Working today</span>
            </div>
            <ul className="roadmap-list">
              {available.map((item) => (
                <li key={item.title} className="roadmap-item roadmap-item--available">
                  <Check className="roadmap-item-icon" size={18} aria-hidden="true" />
                  <div>
                    <h3 className="roadmap-item-title">{item.title}</h3>
                    <p className="roadmap-item-desc">{item.desc}</p>
                  </div>
                </li>
              ))}
            </ul>
          </motion.div>

          <motion.div
            className="roadmap-column roadmap-column--next"
            role="listitem"
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-100px' }}
            transition={{ duration: 0.5, delay: 0.12 }}
          >
            <div className="roadmap-column-head">
              <span className="roadmap-column-label">COMING SOON</span>
              <span className="roadmap-column-title">Not built yet</span>
            </div>
            <ul className="roadmap-list">
              {next.map((item) => (
                <li key={item.title} className="roadmap-item">
                  <div>
                    <h3 className="roadmap-item-title">{item.title}</h3>
                    <p className="roadmap-item-desc">{item.desc}</p>
                  </div>
                  <span className="roadmap-badge">COMING SOON</span>
                </li>
              ))}
            </ul>
          </motion.div>

          <motion.div
            className="roadmap-column roadmap-column--later"
            role="listitem"
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-100px' }}
            transition={{ duration: 0.5, delay: 0.24 }}
          >
            <div className="roadmap-column-head">
              <span className="roadmap-column-label">COMING SOON</span>
              <span className="roadmap-column-title">Further out</span>
            </div>
            <ul className="roadmap-list">
              {later.map((item) => (
                <li key={item.title} className="roadmap-item">
                  <div>
                    <h3 className="roadmap-item-title">{item.title}</h3>
                    <p className="roadmap-item-desc">{item.desc}</p>
                  </div>
                  <span className="roadmap-badge">COMING SOON</span>
                </li>
              ))}
            </ul>
          </motion.div>
        </div>
      </div>
    </section>
  )
}
