import { motion } from 'framer-motion'
import { Mic, FileText, Brain, Search, CheckCircle } from 'lucide-react'

const steps = [
  {
    number: '01',
    icon: Mic,
    title: 'CAPTURE',
    description:
      'Microphone audio is streamed to the transcription service over a WebSocket. Interim results stream in while the sentence is still being spoken.',
    details: ['Realtime audio streaming', 'Interim + final segments', 'Auto-resume on drop'],
  },
  {
    number: '02',
    icon: FileText,
    title: 'TRANSCRIBE',
    description:
      'Speech becomes text in real time. Final segments are forwarded to the claim engine; interim segments only update the on-screen transcript.',
    details: ['Timestamps per segment', 'Speaker labels', 'Automatic punctuation'],
  },
  {
    number: '03',
    icon: Brain,
    title: 'EXTRACT',
    description:
      'An LLM reads the recent transcript and pulls out the factual assertions, batching nearby segments into a single request to stay within rate limits.',
    details: ['Claim vs. opinion split', 'Entity and time context', 'Search-hint generation'],
  },
  {
    number: '04',
    icon: Search,
    title: 'SEARCH',
    description:
      'Each claim becomes a focused query sent to the search provider. Results come back as snippets, URLs and relevance scores.',
    details: ['Dynamic query building', 'Live web search', 'Attributed snippets'],
  },
  {
    number: '05',
    icon: CheckCircle,
    title: 'VERIFY',
    description:
      'The verification engine weighs the retrieved evidence against the claim and returns a verdict with reasoning and the sources behind it.',
    details: ['Stance detection', 'Numeric comparison', 'TRUE / FALSE / UNVERIFIABLE / AMBIGUOUS'],
  },
]

export function HowItWorks() {
  return (
    <section className="how-it-works" id="how-it-works" aria-labelledby="how-title">
      <div className="container">
        <motion.div
          className="section-header section-header--center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5 }}
        >
          <span className="section-eyebrow">HOW IT WORKS</span>
          <h2 id="how-title" className="section-title">
            A real-time verification pipeline.
          </h2>
          <p className="section-description">
            Five stages between a sentence being spoken and a verdict being shown.
          </p>
        </motion.div>

        <div className="steps" role="list">
          {steps.map((step, index) => (
            <motion.article
              key={step.number}
              className="step"
              role="listitem"
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-100px' }}
              transition={{ duration: 0.5, delay: index * 0.08 }}
            >
              <div className="step__number">{step.number}</div>
              <div className="step__icon">
                <step.icon size={26} strokeWidth={1.8} aria-hidden="true" />
              </div>
              <h3 className="step__title">{step.title}</h3>
              <p className="step__description">{step.description}</p>
              <ul className="step__details">
                {step.details.map((detail) => (
                  <li key={detail}>{detail}</li>
                ))}
              </ul>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  )
}
