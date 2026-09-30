import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, Mic, Search, FileText } from 'lucide-react'

const stages = [
  { label: 'LIVE TRANSCRIPT', className: '' },
  { label: 'CLAIM DETECTED', className: 'preview__stage--claim' },
  { label: 'CHECKING EVIDENCE', className: 'preview__stage--checking' },
  { label: 'VERDICT + SOURCES', className: 'preview__stage--result' },
]

export function Hero() {
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero__bg" aria-hidden="true">
        <motion.div
          className="hero__orb hero__orb--1"
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 0.15 }}
          transition={{ duration: 1.2, delay: 0.3, ease: [0.2, 0.7, 0.3, 1] }}
        />
        <motion.div
          className="hero__orb hero__orb--2"
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 0.08 }}
          transition={{ duration: 1.5, delay: 0.6, ease: [0.2, 0.7, 0.3, 1] }}
        />
      </div>

      <div className="hero__content">
        <motion.div
          className="hero__eyebrow"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
        >
          <span className="hero__eyebrow-dot" aria-hidden="true" />
          REAL-TIME FACT VERIFICATION
        </motion.div>

        <motion.h1
          id="hero-title"
          className="hero__title"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
        >
          Know what&apos;s true.
          <br />
          <span className="hero__highlight">While it&apos;s being said.</span>
        </motion.h1>

        <motion.p
          className="hero__description"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
        >
          Live Fact-Checker listens to a conversation, extracts the factual claims inside it,
          searches live web sources for each one, and shows a source-backed verdict as the
          conversation happens.
        </motion.p>

        <motion.div
          className="hero__cta-group"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.4 }}
        >
          <Link to="/dashboard" className="button button--primary button--lg hero__cta">
            <span>Start a live check</span>
            <ArrowRight className="hero__cta-arrow" aria-hidden="true" />
          </Link>
          <a href="/#how-it-works" className="button button--secondary button--lg hero__cta-ghost">
            <span>See how it works</span>
            <ArrowRight className="hero__cta-arrow" aria-hidden="true" />
          </a>
        </motion.div>

        <motion.div
          className="hero__trust"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.5 }}
        >
          <div className="hero__trust-items">
            <div className="hero__trust-item">
              <Mic className="hero__trust-icon" aria-hidden="true" />
              <span>Live transcription</span>
            </div>
            <div className="hero__trust-divider" aria-hidden="true" />
            <div className="hero__trust-item">
              <Search className="hero__trust-icon" aria-hidden="true" />
              <span>Live web search</span>
            </div>
            <div className="hero__trust-divider" aria-hidden="true" />
            <div className="hero__trust-item">
              <FileText className="hero__trust-icon" aria-hidden="true" />
              <span>Cited evidence</span>
            </div>
          </div>
        </motion.div>
      </div>

      <motion.div
        className="hero__preview"
        initial={{ opacity: 0, y: 30, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.8, delay: 0.3, ease: [0.2, 0.7, 0.3, 1] }}
      >
        <div
          className="preview"
          role="img"
          aria-label="Illustration of the fact-checking pipeline: live transcript, claim detected, evidence check, verdict with sources"
        >
          <div className="preview__chrome">
            <div className="preview__chrome-dots">
              <span aria-hidden="true" />
              <span aria-hidden="true" />
              <span aria-hidden="true" />
            </div>
            <div className="preview__chrome-title">LIVE FACT-CHECKER</div>
            <div className="preview__chrome-status">
              <span className="preview__status-dot preview__status-dot--live" aria-hidden="true" />
              <span className="preview__status-text">ILLUSTRATION</span>
            </div>
          </div>

          <div className="preview__body">
            <div className="preview__panel preview__panel--transcript">
              <div className="preview__panel-header">
                <span className="preview__panel-title">LIVE TRANSCRIPT</span>
                <span className="preview__panel-speaker">Speaker 1</span>
              </div>
              <div className="preview__transcript-text">
                <motion.span
                  className="preview__transcript-line"
                  animate={{ opacity: [1, 0.7, 1] }}
                  transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                >
                  &ldquo;A statement worth checking.&rdquo;
                </motion.span>
              </div>
            </div>

            <div className="preview__arrow" aria-hidden="true">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </div>

            <div className="preview__panel preview__panel--pipeline">
              {stages.map((stage, index) => (
                <motion.div
                  key={stage.label}
                  className={`preview__stage ${stage.className}`}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, delay: 0.5 + index * 0.3, ease: [0.2, 0.7, 0.3, 1] }}
                >
                  <div className="preview__stage-header">
                    <span className="preview__stage-label">{stage.label}</span>
                    {stage.className.includes('checking') && (
                      <span className="preview__spinner" aria-hidden="true" />
                    )}
                    {stage.className.includes('result') && (
                      <span className="preview__stage-sources" aria-hidden="true">
                        3 sources
                      </span>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </motion.div>
    </section>
  )
}
