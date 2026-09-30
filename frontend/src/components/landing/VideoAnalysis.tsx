import { motion } from 'framer-motion'
import { Upload, FileText, Users, ListChecks, ShieldCheck, LayoutGrid } from 'lucide-react'

import { SectionSurface, accentClass, surfaceClass } from './tone'

/** Stages a recording moves through, matching the implemented ingestion path. */
const STEPS = [
  { label: 'Upload video', icon: Upload },
  { label: 'Transcript', icon: FileText },
  { label: 'Speaker detection', icon: Users },
  { label: 'Claim extraction', icon: ListChecks },
  { label: 'Per-claim verification', icon: ShieldCheck },
  { label: 'Video scorecard', icon: LayoutGrid },
]

/**
 * Counts are illustrative placeholders for a *layout* preview, not results from
 * a real analysis. No aggregate "truth score" is shown: a video is summarised by
 * how many claims landed in each verdict bucket, and nothing more.
 */
const BUCKETS = [
  { label: 'TRUE', key: 'true', value: 11, tone: 'true' },
  { label: 'FALSE', key: 'false', value: 5, tone: 'false' },
  { label: 'UNVERIFIABLE', key: 'unverifiable', value: 3, tone: 'unverifiable' },
  { label: 'AMBIGUOUS', key: 'ambiguous', value: 1, tone: 'ambiguous' },
]

const TOTAL = BUCKETS.reduce((sum, bucket) => sum + bucket.value, 0)

export function VideoAnalysis({ surface = 'charcoal' }: { surface?: SectionSurface }) {
  return (
    <section id="video" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container">
        <span className="lfp-eyebrow">VIDEO ANALYSIS</span>
        <h2 className="lfp-h2 lfp-h2--center">Fact-check an entire video.</h2>
        <p className="lfp-lede lfp-lede--center">
          Every claim is checked on its own. The scorecard is a count of outcomes, not
          a single judgement about the video.
        </p>

        <ol className="lfp-vsteps">
          {STEPS.map((step, index) => {
            const Icon = step.icon
            return (
              <motion.li
                key={step.label}
                className="lfp-vsteps__item"
                initial={{ opacity: 0, y: 14 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-60px' }}
                transition={{ duration: 0.42, delay: index * 0.08 }}
              >
                <span className="lfp-vsteps__icon" aria-hidden="true">
                  <Icon size={18} strokeWidth={1.5} />
                </span>
                <span className="lfp-vsteps__label">{step.label}</span>
              </motion.li>
            )
          })}
        </ol>

        <motion.div
          className="lfp-scorecard"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.55, ease: [0.2, 0.7, 0.3, 1] }}
        >
          <div className="lfp-scorecard__head">
            <div>
              <p className="lfp-scorecard__title">Video report</p>
              <p className="lfp-scorecard__sub">
                {TOTAL} claims analysed · layout preview
              </p>
            </div>
            <span className="lfp-window__tag">ILLUSTRATIVE PREVIEW</span>
          </div>

          <div className="lfp-scorecard__grid">
            {BUCKETS.map((bucket) => (
              <div key={bucket.key} className={`lfp-scorecard__cell lfp-scorecard__cell--${bucket.tone}`}>
                <span className="lfp-scorecard__count">{bucket.value}</span>
                <span className="lfp-scorecard__label">{bucket.label}</span>
              </div>
            ))}
          </div>

          <dl className="lfp-scorecard__meta">
            <div>
              <dt>Coverage</dt>
              <dd>
                {BUCKETS.slice(0, 3).reduce((sum, b) => sum + b.value, 0)} of {TOTAL} claims produced
                a verdict
              </dd>
            </div>
            <div>
              <dt>Failed checks</dt>
              <dd>Retrieval errors are reported separately, never as a verdict</dd>
            </div>
            <div>
              <dt>Timestamps</dt>
              <dd>Every claim carries the offset where it was said</dd>
            </div>
            <div>
              <dt>Speakers</dt>
              <dd>Preserved when the transcription provides them</dd>
            </div>
            <div>
              <dt>Sources</dt>
              <dd>Listed per claim, and traceable to the retrieved snippets</dd>
            </div>
            <div>
              <dt>No truth score</dt>
              <dd>A video is not scored; each claim is judged on its evidence</dd>
            </div>
          </dl>
        </motion.div>
      </div>
    </section>
  )
}

/** Architecture, animated slowly top to bottom. */
const NODES = [
  { label: 'MICROPHONE / AUDIO / VIDEO / URL', accent: 'green' },
  { label: 'ASSEMBLYAI', accent: 'blue' },
  { label: 'QWEN', accent: 'lavender' },
  { label: 'TAVILY', accent: 'green' },
  { label: 'VERIFICATION ENGINE', accent: 'yellow' },
  { label: 'SUPABASE', accent: 'orange' },
  { label: 'LIVE FACT CHECKER', accent: 'green' },
] as const


export function Technology({ surface = 'charcoal' }: { surface?: SectionSurface }) {
  return (
    <section id="technology" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container">
        <span className="lfp-eyebrow">TECHNOLOGY</span>
        <h2 className="lfp-h2 lfp-h2--center">Built on real-time AI infrastructure.</h2>
        <p className="lfp-lede lfp-lede--center">
          Each stage is a real service doing a real job. The diagram is the actual
          request path.
        </p>

        <div className="lfp-arch">
          {NODES.map((node, index) => (
            <motion.div
              key={node.label}
              className={`lfp-arch__node ${accentClass(node.accent)}`}
              initial={{ opacity: 0, y: 10 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.45, delay: index * 0.11 }}
            >
              <span className="lfp-arch__label">{node.label}</span>
              {index < NODES.length - 1 ? (
                <span className="lfp-arch__link" aria-hidden="true">
                  <motion.i
                    initial={{ scaleY: 0 }}
                    whileInView={{ scaleY: 1 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.45, delay: 0.2 + index * 0.11 }}
                  />
                </span>
              ) : null}
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}

const CAPABILITIES = [
  {
    title: 'REAL-TIME',
    accent: 'green',
    body: 'Evidence-backed fact checking during live speech.',
  },
  {
    title: 'MULTI-FORMAT',
    accent: 'orange',
    body: 'Microphone, audio, video and URL ingestion.',
  },
  {
    title: 'SPEAKER-AWARE',
    accent: 'lavender',
    body: 'Preserve speaker information when available.',
  },
  {
    title: 'TIMESTAMP-AWARE',
    accent: 'yellow',
    body: 'Know exactly where a claim occurred.',
  },
  {
    title: 'SOURCE-LINKED',
    accent: 'blue',
    body: 'Every verification can expose retrieved sources.',
  },
  {
    title: 'AMBIGUOUS',
    accent: 'red',
    body: 'Separate unclear claims from confirmed results.',
  },
] as const

export function Capabilities({ surface = 'beige' }: { surface?: SectionSurface }) {
  return (
    <section id="capabilities" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container">
        <span className="lfp-eyebrow">CAPABILITIES</span>
        <h2 className="lfp-h2 lfp-h2--center">What the pipeline guarantees.</h2>

        <div className="lfp-caps">
          {CAPABILITIES.map((capability, index) => (
            <motion.article
              key={capability.title}
              className={`lfp-card lfp-card--tint lfp-caps__card ${accentClass(capability.accent)}`}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: 0.42, delay: index * 0.06 }}
            >
              <h3 className="lfp-card__title lfp-card__title--sm">{capability.title}</h3>
              <p className="lfp-card__body">{capability.body}</p>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  )
}
