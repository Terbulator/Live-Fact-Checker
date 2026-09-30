import { motion } from 'framer-motion'
import { FileText, Search, Link as LinkIcon, CheckCircle, HelpCircle } from 'lucide-react'

const evidenceFlow = [
  {
    step: 'CLAIM',
    icon: FileText,
    description: 'A checkable statement is pulled out of live speech',
    example: 'Speaker: "Twelve thousand homes were approved this year."',
  },
  {
    step: 'QUERY',
    icon: Search,
    description: 'The claim is turned into a search built for the current web',
    example: 'Query: "housing approvals total this year"',
  },
  {
    step: 'EVIDENCE',
    icon: LinkIcon,
    description: 'Results are parsed into attributed snippets and kept with their URLs',
    example: '3 results · 2 official, 1 news',
  },
  {
    step: 'VERDICT',
    icon: CheckCircle,
    description: 'The evidence is weighed against the claim, and the sources ship with the answer',
    example: 'FALSE · 2 sources contradict the claim',
  },
]

export function EvidenceSection() {
  return (
    <section className="evidence-section" id="evidence" aria-labelledby="evidence-title">
      <div className="container">
        <motion.div
          className="section-header section-header--center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5 }}
        >
          <span className="section-eyebrow">EVIDENCE TRAIL</span>
          <h2 id="evidence-title" className="section-title">
            Every verdict carries its sources.
          </h2>
          <p className="section-description">
            A verdict on its own is an opinion. Each one here is shown with the sources that
            produced it, so you can open them and check the check.
          </p>
        </motion.div>

        <motion.div
          className="evidence-flow"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5, delay: 0.1 }}
          role="list"
        >
          {evidenceFlow.map((item, index) => (
            <motion.div
              key={item.step}
              className="evidence-step"
              role="listitem"
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: 0.1 + index * 0.1 }}
            >
              <div className="evidence-step-icon">
                <item.icon size={24} strokeWidth={1.8} aria-hidden="true" />
              </div>
              <div className="evidence-step-label">{item.step}</div>
              <p className="evidence-step-desc">{item.description}</p>
              <code className="evidence-step-example">{item.example}</code>
            </motion.div>
          ))}
        </motion.div>

        <motion.div
          className="evidence-principle"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5, delay: 0.3 }}
        >
          <div className="evidence-principle-content">
            <HelpCircle className="evidence-principle-icon" size={28} aria-hidden="true" />
            <div className="evidence-principle-text">
              <strong>Weak evidence gets a weak answer.</strong>
              <p>
                When the sources do not settle a claim, the result is UNVERIFIABLE or
                AMBIGUOUS rather than a confident guess. Those two verdicts exist so the
                system never has to bluff.
              </p>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
