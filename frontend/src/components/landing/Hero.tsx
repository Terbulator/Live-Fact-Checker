import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, CheckCircle2 } from 'lucide-react'

import { surfaceClass } from './tone'

/**
 * Marketing hero.
 *
 * The product surface below the copy is a *visualisation*, not the live
 * dashboard. It is static, self-contained markup: no session, no WebSocket, no
 * backend call, and no shared state with `/dashboard`. The "Illustrative
 * preview" tag makes that explicit on screen.
 */

const TRANSCRIPT = 'India won the 2011 World Cup.'

/** Generic source rows. The live product lists whatever search returned. */
const SOURCES = [
  { name: 'ICC', detail: 'Tournament archive' },
  { name: 'ESPNcricinfo', detail: 'Match report' },
  { name: 'Wikipedia', detail: '2011 Cricket World Cup' },
]

/** Rung-by-rung reveal for the product preview. Purely visual timing. */
const STEPS = [
  { at: 0.35, label: 'Listening' },
  { at: 0.9, label: 'Transcript' },
  { at: 1.5, label: 'Extracted claim' },
  { at: 2.1, label: 'Evidence retrieved' },
  { at: 2.7, label: 'Verdict' },
]

export function Hero() {
  return (
    <section id="product" className={`lfp-hero ${surfaceClass('paper')}`}>
      <div className="lfp-container">
        <div className="lfp-hero__copy">
          <span className="lfp-eyebrow">REAL-TIME AI FACT CHECKING</span>
          <h1 className="lfp-h1">
            Fact-check anything.
            <br />
            <span className="lfp-h1__accent">While it is happening.</span>
          </h1>
          <p className="lfp-lede">
            Turn live speech, audio, video and online content into evidence-backed facts.
          </p>
          <div className="lfp-hero__actions">
            <Link to="/dashboard" className="lfp-btn lfp-btn--primary lfp-btn--invert lfp-btn--lg">
              Start for Free
              <ArrowRight size={17} aria-hidden="true" />
            </Link>
            <a href="#pipeline" className="lfp-btn lfp-btn--ghost lfp-btn--lg">
              See how it works
            </a>
          </div>
          <p className="lfp-hero__note">
            Runs the real pipeline. Nothing is preloaded — results appear only after you
            speak or upload.
          </p>
        </div>

        {/*
          Product preview. Marked as an illustration and kept entirely
          independent of application state so it can never be mistaken for a
          live session.
        */}
        <motion.div
          className="lfp-hero__stage"
          initial={{ opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.15, ease: [0.2, 0.7, 0.3, 1] }}
        >
          <div className="lfp-window">
            <div className="lfp-window__bar">
              <span className="lfp-window__dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              <span className="lfp-window__title">LIVE FACT-CHECKER</span>
              <span className="lfp-window__tag">ILLUSTRATIVE PREVIEW</span>
            </div>

            <div className="lfp-window__body">
              <div className="lfp-preview__left">
                <div className="lfp-preview__status">
                  <span className="lfp-dot" aria-hidden="true" />
                  LIVE
                  <span className="lfp-preview__statusText">Listening…</span>
                </div>

                <p className="lfp-preview__label">TRANSCRIPT</p>
                <p className="lfp-preview__transcript">
                  <span className="lfp-preview__caret" aria-hidden="true" />
                  {TRANSCRIPT}
                </p>
              </div>

              <div className="lfp-preview__right">
                <p className="lfp-preview__label">VERIFICATION</p>

                <motion.div
                  className="lfp-verdict lfp-verdict--true"
                  initial={{ opacity: 0, scale: 0.96 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.45, delay: 1.1, ease: [0.2, 0.7, 0.3, 1] }}
                >
                  <CheckCircle2 size={18} aria-hidden="true" />
                  <span>TRUE</span>
                </motion.div>

                <p className="lfp-preview__confidence">
                  <span>CONFIDENCE</span>
                  <strong>Provider score</strong>
                </p>

                <p className="lfp-preview__label">SOURCES</p>
                <ul className="lfp-preview__sources">
                  {SOURCES.map((source, index) => (
                    <motion.li
                      key={source.name}
                      initial={{ opacity: 0, x: 8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{
                        duration: 0.35,
                        delay: 1.5 + index * 0.16,
                        ease: [0.2, 0.7, 0.3, 1],
                      }}
                    >
                      <span className="lfp-preview__sourceName">{source.name}</span>
                      <span className="lfp-preview__sourceDetail">{source.detail}</span>
                    </motion.li>
                  ))}
                </ul>
              </div>
            </div>
          </div>

          {/* Progress rail mirrors the real pipeline order. */}
          <ol className="lfp-hero__rail" aria-label="Pipeline progress illustration">
            {STEPS.map((step) => (
              <motion.li
                key={step.label}
                initial={{ opacity: 0.25 }}
                animate={{ opacity: [0.25, 1, 0.55] }}
                transition={{
                  duration: 1.2,
                  delay: step.at,
                  repeat: Infinity,
                  repeatDelay: 3.2,
                  ease: 'easeInOut',
                }}
              >
                {step.label}
              </motion.li>
            ))}
          </ol>
        </motion.div>
      </div>
    </section>
  )
}
