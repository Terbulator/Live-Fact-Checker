import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import { CheckCircle, XCircle, HelpCircle, Loader2 } from 'lucide-react'

type ClaimStatus = 'checking' | 'supported' | 'refuted' | 'unknown'

interface DemoClaim {
  id: string
  text: string
  status: ClaimStatus
  verdict: string | null
  sources: { domain: string; note: string }[]
}

const transcriptLines = [
  { speaker: 'Speaker 1', text: 'The city just published its new housing figures.' },
  { speaker: 'Speaker 1', text: 'It says twelve thousand homes were approved this year.' },
  { speaker: 'Speaker 2', text: 'I only heard about four thousand.' },
  { speaker: 'Speaker 1', text: 'And the whole thing cost under fifty million.' },
]

const claims: DemoClaim[] = [
  {
    id: 'claim-1',
    text: 'The city just published its new housing figures.',
    status: 'supported',
    verdict: 'TRUE',
    sources: [{ domain: 'example.gov', note: 'Publication notice matches the stated date.' }],
  },
  {
    id: 'claim-2',
    text: 'It says twelve thousand homes were approved this year.',
    status: 'refuted',
    verdict: 'FALSE',
    sources: [
      { domain: 'example.gov', note: 'Official count lists 4,100 approvals.' },
      { domain: 'example-news.org', note: 'Coverage repeats the 4,100 figure.' },
    ],
  },
  {
    id: 'claim-3',
    text: 'And the whole thing cost under fifty million.',
    status: 'unknown',
    verdict: 'UNVERIFIABLE',
    sources: [{ domain: 'example-news.org', note: 'No published budget total found.' }],
  },
  {
    id: 'claim-4',
    text: 'I only heard about four thousand.',
    status: 'checking',
    verdict: null,
    sources: [],
  },
]

const verdictIcon: Record<Exclude<ClaimStatus, 'checking'>, typeof CheckCircle> = {
  supported: CheckCircle,
  refuted: XCircle,
  unknown: HelpCircle,
}

export function LiveDemo() {
  return (
    <section className="live-demo" id="demo" aria-labelledby="demo-title">
      <div className="container">
        <motion.div
          className="section-header section-header--center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5 }}
        >
          <span className="section-eyebrow">SESSION WALKTHROUGH</span>
          <h2 id="demo-title" className="section-title">
            From spoken words to evidence.
          </h2>
          <p className="section-description">
            The transcript arrives first, claims are pulled out of it, each one is checked
            against live sources, and the verdict appears with the evidence that produced it.
          </p>
        </motion.div>

        <motion.div
          className="demo-frame"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.6 }}
        >
          <div className="demo-chrome">
            <div className="demo-chrome-dots">
              <span aria-hidden="true" />
              <span aria-hidden="true" />
              <span aria-hidden="true" />
            </div>
            <div className="demo-chrome-title">LIVE FACT-CHECKER</div>
            <div className="demo-chrome-status">
              <span className="demo-status-dot demo-status-dot--live" aria-hidden="true" />
              <span className="demo-status-text">ILLUSTRATIVE SAMPLE</span>
            </div>
          </div>

          <div className="demo-body">
            <div className="demo-panel demo-panel--transcript">
              <div className="demo-panel-header">
                <span className="demo-panel-title">LIVE TRANSCRIPT</span>
                <div className="demo-panel-speakers">
                  {['Speaker 1', 'Speaker 2'].map((speaker) => (
                    <span key={speaker} className="demo-speaker-badge">
                      {speaker}
                    </span>
                  ))}
                </div>
              </div>
              <div className="demo-transcript">
                {transcriptLines.map((line, index) => (
                  <motion.div
                    key={line.text}
                    className="demo-transcript-line"
                    initial={{ opacity: 0, x: -20 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.3, delay: 0.2 + index * 0.15 }}
                  >
                    <span className="demo-line-speaker">{line.speaker}</span>
                    <p className="demo-line-text">{line.text}</p>
                  </motion.div>
                ))}
                <motion.div
                  className="demo-transcript-line demo-line--incoming"
                  animate={{ opacity: [0.4, 1, 0.4] }}
                  transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
                >
                  <span className="demo-line-speaker">Speaker 1</span>
                  <p className="demo-line-text">And they said it would be done by autumn...</p>
                </motion.div>
              </div>
            </div>

            <div className="demo-panel demo-panel--claims">
              <div className="demo-panel-header">
                <span className="demo-panel-title">CLAIMS UNDER CHECK</span>
                <span className="demo-panel-count">{claims.length} claims</span>
              </div>
              <div className="demo-claims">
                {claims.map((claim, index) => {
                  const Icon =
                    claim.status === 'checking' ? Loader2 : verdictIcon[claim.status as Exclude<ClaimStatus, 'checking'>]

                  return (
                    <motion.article
                      key={claim.id}
                      className={`demo-claim-card demo-claim-card--${claim.status}`}
                      initial={{ opacity: 0, y: 20 }}
                      whileInView={{ opacity: 1, y: 0 }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.3, delay: 0.5 + index * 0.2 }}
                    >
                      <div className="demo-claim-header">
                        <span className={`demo-claim-status demo-claim-status--${claim.status}`}>
                          <Icon
                            className={claim.status === 'checking' ? 'demo-spinner' : undefined}
                            size={14}
                            aria-hidden="true"
                          />
                          <span>{claim.verdict ?? 'CHECKING'}</span>
                        </span>
                      </div>
                      <p className="demo-claim-text">&ldquo;{claim.text}&rdquo;</p>
                      {claim.sources.length > 0 && (
                        <div className="demo-evidence">
                          {claim.sources.map((source) => (
                            <div key={source.domain} className="demo-evidence-source">
                              <span className="demo-evidence-domain">{source.domain}</span>
                              <p className="demo-evidence-snippet">{source.note}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </motion.article>
                  )
                })}
              </div>
            </div>
          </div>
        </motion.div>

        <motion.div
          className="demo-caption"
          initial={{ opacity: 0, y: 10 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.4, delay: 0.8 }}
        >
          This is an illustrative example, not a recorded session. Real sessions use live
          results from your own audio. <Link to="/dashboard" className="demo-caption-link">Run one →</Link>
        </motion.div>
      </div>
    </section>
  )
}
