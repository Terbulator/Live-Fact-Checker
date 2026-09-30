import { motion } from 'framer-motion'
import { Mic, AudioLines, Video, Link2, SearchCheck, MessageSquareQuote } from 'lucide-react'

import { SectionSurface, accentClass, surfaceClass } from './tone'

/** The four pipeline stages, in the order the product actually runs them. */
const STAGES = [
  {
    n: '01',
    title: 'CAPTURE',
    body: 'Live microphone, audio, video or URL.',
    icon: Mic,
    accent: 'green',
  },
  {
    n: '02',
    title: 'UNDERSTAND',
    body: 'AssemblyAI transcribes the content. Qwen extracts checkable claims.',
    icon: AudioLines,
    accent: 'blue',
  },
  {
    n: '03',
    title: 'VERIFY',
    body: 'Tavily retrieves live evidence.',
    icon: SearchCheck,
    accent: 'yellow',
  },
  {
    n: '04',
    title: 'EXPLAIN',
    body: 'Return verdict, confidence, supporting statement and sources.',
    icon: MessageSquareQuote,
    accent: 'lavender',
  },
] as const

export function PipelineSection({ surface = 'beige' }: { surface?: SectionSurface }) {
  return (
    <section id="pipeline" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container">
        <span className="lfp-eyebrow">THE PIPELINE</span>
        <h2 className="lfp-h2 lfp-h2--center">From speech to verified facts.</h2>
        <p className="lfp-lede lfp-lede--center">
          Four stages, every time. Nothing is skipped when the answer is inconvenient.
        </p>

        <ol className="lfp-pipeline">
          {STAGES.map((stage, index) => {
            const Icon = stage.icon
            return (
              <motion.li
                key={stage.n}
                className={`lfp-pipeline__stage ${accentClass(stage.accent)}`}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-80px' }}
                transition={{
                  duration: 0.5,
                  delay: index * 0.1,
                  ease: [0.2, 0.7, 0.3, 1],
                }}
              >
                <span className="lfp-pipeline__number">{stage.n}</span>
                <span className="lfp-pipeline__icon" aria-hidden="true">
                  <Icon size={20} strokeWidth={1.5} />
                </span>
                <h3 className="lfp-pipeline__title">{stage.title}</h3>
                <p className="lfp-pipeline__body">{stage.body}</p>

                {/* Connector draws itself once the stage is on screen. */}
                {index < STAGES.length - 1 ? (
                  <span className="lfp-pipeline__line" aria-hidden="true">
                    <motion.i
                      initial={{ scaleX: 0 }}
                      whileInView={{ scaleX: 1 }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.6, delay: 0.25, ease: [0.2, 0.7, 0.3, 1] }}
                    />
                  </span>
                ) : null}
              </motion.li>
            )
          })}
        </ol>
      </div>
    </section>
  )
}

const INPUTS = [
  {
    title: 'LIVE MICROPHONE',
    body: 'Fact-check speech as it happens.',
    icon: Mic,
    meta: 'Realtime · streaming',
    accent: 'green',
  },
  {
    title: 'AUDIO',
    body: 'Upload recorded conversations, podcasts or audio.',
    icon: AudioLines,
    meta: 'MP3 · WAV · M4A · OGG · FLAC',
    accent: 'blue',
  },
  {
    title: 'VIDEO',
    body: 'Analyze recorded video with speakers and timestamps.',
    icon: Video,
    meta: 'MP4 · MOV · WebM · AVI · MKV',
    accent: 'lavender',
  },
  {
    title: 'VIDEO / URL',
    body: 'Analyze online video content.',
    icon: Link2,
    meta: 'Direct link or YouTube URL',
    accent: 'orange',
  },
] as const

export function InputTypes({ surface = 'white' }: { surface?: SectionSurface }) {
  return (
    <section id="inputs" className={`lfp-section ${surfaceClass(surface)}`}>
      <div className="lfp-container">
        <span className="lfp-eyebrow">INPUT TYPES</span>
        <h2 className="lfp-h2 lfp-h2--center">One pipeline, four ways in.</h2>
        <p className="lfp-lede lfp-lede--center">
          Every input runs the same transcription, extraction and verification stages.
        </p>

        <div className="lfp-inputs">
          {INPUTS.map((item, index) => {
            const Icon = item.icon
            return (
              <motion.article
                key={item.title}
                className={`lfp-card lfp-card--tint lfp-inputs__card ${accentClass(item.accent)}`}
                initial={{ opacity: 0, y: 18 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-60px' }}
                transition={{
                  duration: 0.45,
                  delay: index * 0.07,
                  ease: [0.2, 0.7, 0.3, 1],
                }}
              >
                <span className="lfp-card__icon" aria-hidden="true">
                  <Icon size={22} strokeWidth={1.5} />
                </span>
                <h3 className="lfp-card__title">{item.title}</h3>
                <p className="lfp-card__body">{item.body}</p>
                <span className="lfp-card__meta">{item.meta}</span>
              </motion.article>
            )
          })}
        </div>
      </div>
    </section>
  )
}
