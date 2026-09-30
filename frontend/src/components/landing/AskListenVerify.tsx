import { motion } from 'framer-motion'

import { SectionSurface, surfaceClass, VERDICTS } from './tone'

/**
 * Ask / Listen / Verify — a marketing visualisation of one moment in the
 * product.
 *
 * This is illustrative copy describing how the interface behaves, not a session
 * and not a stored result. It is static markup with no backend call and no
 * shared state, and it is labelled on screen so it cannot be read as a live
 * verification.
 */

const TURNS = [
  { speaker: 'Speaker 1', time: '00:41', text: 'The Eiffel Tower is right there in India.' },
  { speaker: 'Speaker 2', time: '00:48', text: 'It is one of the most visited monuments on earth.' },
  { speaker: 'Speaker 1', time: '00:52', text: 'It took three years to build.' },
]

export function AskListenVerify({ surface = 'charcoal' }: { surface?: SectionSurface }) {
  return (
    <section id="verify" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container">
        <span className="lfp-eyebrow">LISTEN · EXTRACT · VERIFY</span>
        <h2 className="lfp-h2 lfp-h2--center">The moment a claim gets checked.</h2>
        <p className="lfp-lede lfp-lede--center">
          A sentence is pulled out of the conversation, searched, and answered with the
          evidence that decided it.
        </p>

        <div className="lfp-verify">
          {/* Left: the transcript as it would appear live. */}
          <motion.div
            className="lfp-verify__pane"
            initial={{ opacity: 0, x: -18 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ duration: 0.5, ease: [0.2, 0.7, 0.3, 1] }}
          >
            <div className="lfp-verify__bar">
              <span className="lfp-verify__barTitle">LIVE TRANSCRIPT</span>
              <span className="lfp-window__tag">ILLUSTRATIVE PREVIEW</span>
            </div>
            <ol className="lfp-verify__turns">
              {TURNS.map((turn, index) => (
                <motion.li
                  key={turn.time}
                  className={
                    index === 0 ? 'lfp-verify__turn lfp-verify__turn--active' : 'lfp-verify__turn'
                  }
                  initial={{ opacity: 0, y: 8 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.4, delay: index * 0.12 }}
                >
                  <span className="lfp-verify__meta">
                    {turn.speaker} · {turn.time}
                  </span>
                  <p>{turn.text}</p>
                </motion.li>
              ))}
            </ol>
          </motion.div>

          {/* Right: the verdict that search would produce. */}
          <motion.div
            className="lfp-verify__pane lfp-verify__pane--result"
            initial={{ opacity: 0, x: 18 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ duration: 0.5, delay: 0.1, ease: [0.2, 0.7, 0.3, 1] }}
          >
            <p className="lfp-preview__label">EXTRACTED CLAIM</p>
            <p className="lfp-verify__claim">The Eiffel Tower is located in India.</p>

            <div className="lfp-verdict lfp-verdict--false">
              <span className="lfp-verdict__glyph" aria-hidden="true">
                {VERDICTS.false.glyph}
              </span>
              <span>{VERDICTS.false.label}</span>
            </div>

            <p className="lfp-preview__label">EVIDENCE</p>
            <p className="lfp-verify__evidence">
              Retrieved sources place the monument in Paris, France. The claim states a
              different country.
            </p>

            <dl className="lfp-verify__facts">
              <div>
                <dt>Source</dt>
                <dd>Retrieved reference source</dd>
              </div>
              <div>
                <dt>Timestamp</dt>
                <dd>00:48</dd>
              </div>
              <div>
                <dt>Speaker</dt>
                <dd>Speaker 1</dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>Provider score, or N/A when none is reported</dd>
              </div>
            </dl>
          </motion.div>
        </div>
      </div>
    </section>
  )
}
