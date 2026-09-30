import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Plus } from 'lucide-react'

import { SectionSurface, accentClass, surfaceClass } from './tone'

/**
 * Trust, FAQ, closing call to action and footer.
 *
 * Every claim in the trust section describes behaviour the code actually
 * implements. No security, compliance or certification claims are made, because
 * none are attested.
 */

const GUARANTEES = [
  {
    accent: 'green',
    title: 'Sources stay visible',
    body: 'A verdict is shown with the retrieved sources that produced it, so the answer can be inspected rather than trusted.',
  },
  {
    accent: 'blue',
    title: 'Supporting statements are grounded',
    body: 'Explanations are assembled from the retrieved snippets. They are not written from model memory.',
  },
  {
    accent: 'yellow',
    title: 'Confidence can be absent',
    body: 'When the search provider reports no score, the interface shows N/A instead of inventing a number.',
  },
  {
    accent: 'lavender',
    title: 'Ambiguous stays ambiguous',
    body: 'Claims that cannot be resolved to true or false are reported as such rather than forced into a binary answer.',
  },
  {
    accent: 'red',
    title: 'Failed retrieval is not a verdict',
    body: 'A search that errors or returns nothing becomes UNVERIFIABLE. It never becomes a false or a true result.',
  },
] as const

export function TrustSection({ surface = 'paper' }: { surface?: SectionSurface }) {
  return (
    <section id="trust" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container">
        <span className="lfp-eyebrow">CONTROL</span>
        <h2 className="lfp-h2 lfp-h2--center">Evidence stays visible.</h2>
        <p className="lfp-lede lfp-lede--center">
          The interface is built so a result can be checked rather than believed.
        </p>

        <div className="lfp-trust">
          {GUARANTEES.map((item, index) => (
            <motion.article
              key={item.title}
              className={`lfp-card lfp-card--tint lfp-trust__card ${accentClass(item.accent)}`}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.45, delay: index * 0.07 }}
            >
              <span className="lfp-trust__mark" aria-hidden="true" />
              <h3 className="lfp-card__title lfp-card__title--sm">{item.title}</h3>
              <p className="lfp-card__body">{item.body}</p>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  )
}

const FAQS = [
  {
    q: 'What can Live Fact Checker analyze?',
    a: 'Live microphone speech, uploaded audio files, uploaded video files, and online video addressed by URL. All four run the same transcription, claim extraction and verification stages.',
  },
  {
    q: 'How does live fact checking work?',
    a: 'Speech is transcribed as it is finalized. Only finalized lines are checked. Extracted claims are searched against live sources, and the verdict is returned with the evidence that produced it.',
  },
  {
    q: 'Can I upload audio?',
    a: 'Yes. Recorded conversations, podcasts and other audio are accepted. The transcript is produced from the file, then analysed claim by claim.',
  },
  {
    q: 'Can I upload video?',
    a: 'Yes. Audio is extracted from the video, transcribed, and analysed. Claims keep their timestamps, and speakers are preserved when the transcription provides them.',
  },
  {
    q: 'Can I analyze a video URL?',
    a: 'Yes. A direct video link or a YouTube URL can be analysed through the same ingestion and verification path.',
  },
  {
    q: 'How are claims extracted?',
    a: 'A language model reads the transcript and pulls out statements that can be checked against evidence. Numbers, dates, names and negations are preserved exactly as spoken.',
  },
  {
    q: 'Where does the evidence come from?',
    a: 'A live web search provider returns sources at the moment the claim is checked. Nothing is looked up in a stored library of known facts.',
  },
  {
    q: 'What does AMBIGUOUS mean?',
    a: 'The retrieved evidence does not resolve the claim cleanly, or sources disagree. The result is reported as ambiguous rather than forced into true or false.',
  },
  {
    q: 'What happens if evidence cannot be retrieved?',
    a: 'The claim is reported as UNVERIFIABLE. A failed search never produces a true or false verdict, and no supporting statement is written without a source.',
  },
  {
    q: 'How is confidence displayed?',
    a: 'It mirrors the relevance score reported by the search provider. When no usable score is available, the interface shows N/A rather than substituting a default.',
  },
]

export function Faq({ surface = 'paper' }: { surface?: SectionSurface }) {
  const [open, setOpen] = useState<number | null>(0)

  return (
    <section id="faq" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container lfp-container--narrow">
        <span className="lfp-eyebrow">FAQ</span>
        <h2 className="lfp-h2 lfp-h2--center">Questions, answered.</h2>

        <div className="lfp-faq">
          {FAQS.map((item, index) => {
            const isOpen = open === index
            return (
              <div key={item.q} className={`lfp-faq__item${isOpen ? ' lfp-faq__item--open' : ''}`}>
                <h3>
                  <button
                    type="button"
                    className="lfp-faq__trigger"
                    aria-expanded={isOpen}
                    aria-controls={`lfp-faq-panel-${index}`}
                    onClick={() => setOpen(isOpen ? null : index)}
                  >
                    <span>{item.q}</span>
                    <motion.span
                      className="lfp-faq__icon"
                      animate={{ rotate: isOpen ? 45 : 0 }}
                      transition={{ duration: 0.2 }}
                      aria-hidden="true"
                    >
                      <Plus size={17} />
                    </motion.span>
                  </button>
                </h3>

                <AnimatePresence initial={false}>
                  {isOpen ? (
                    <motion.div
                      id={`lfp-faq-panel-${index}`}
                      className="lfp-faq__panel"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.26, ease: [0.2, 0.7, 0.3, 1] }}
                    >
                      <p>{item.a}</p>
                    </motion.div>
                  ) : null}
                </AnimatePresence>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

export function FinalCTA() {
  return (
    <section className="lfp-cta">
      <div className="lfp-container">
        <motion.div
          className="lfp-cta__inner"
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.6, ease: [0.2, 0.7, 0.3, 1] }}
        >
          <h2 className="lfp-h1 lfp-cta__title">
            Don’t just listen.
            <br />
            <span className="lfp-h1__accent">Verify.</span>
          </h2>
          <p className="lfp-lede lfp-lede--center">
            Turn live speech and recorded content into evidence-backed facts.
          </p>
          <div className="lfp-hero__actions lfp-hero__actions--center">
            <Link to="/dashboard" className="lfp-btn lfp-btn--primary lfp-btn--lg">
              Start for Free
            </Link>
            <Link to="/login" className="lfp-btn lfp-btn--ghost lfp-btn--lg">
              Log in
            </Link>
          </div>
        </motion.div>
      </div>
    </section>
  )
}

const FOOTER_GROUPS = [
  {
    title: 'Product',
    links: [
      { label: 'How it works', href: '#pipeline' },
      { label: 'Features', href: '#capabilities' },
      { label: 'Sources', href: '#sources' },
      { label: 'Video analysis', href: '#video' },
    ],
  },
  {
    title: 'Resources',
    links: [
      { label: 'Documentation', href: '#faq' },
      { label: 'GitHub', href: 'https://github.com' },
    ],
  },
  {
    title: 'Legal',
    links: [
      { label: 'Privacy', href: '#trust' },
      { label: 'Terms', href: '#trust' },
    ],
  },
]

export function Footer() {
  return (
    <footer className="lfp-footer">
      <div className="lfp-container">
        <div className="lfp-footer__top">
          <div className="lfp-footer__brand">
            <span className="lfp-brand__mark" aria-hidden="true" />
            <p className="lfp-footer__wordmark">LIVE FACT CHECKER</p>
            <p className="lfp-footer__tag">
              Real-time claim extraction and evidence-backed verification for speech,
              audio, video and online video.
            </p>
          </div>

          <nav className="lfp-footer__groups" aria-label="Footer">
            {FOOTER_GROUPS.map((group) => (
              <div key={group.title} className="lfp-footer__group">
                <h2 className="lfp-footer__groupTitle">{group.title}</h2>
                <ul>
                  {group.links.map((link) => (
                    <li key={link.label}>
                      <a
                        href={link.href}
                        {...(link.href.startsWith('http')
                          ? { target: '_blank', rel: 'noreferrer noopener' }
                          : {})}
                      >
                        {link.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>

        <div className="lfp-footer__bottom">
          <p>© 2026 Live Fact Checker</p>
          <p className="lfp-footer__disclaimer">
            Verdicts describe what retrieved sources say about a claim. They are not
            legal, medical or financial advice.
          </p>
        </div>
      </div>
    </footer>
  )
}
