import { motion } from 'framer-motion'
import { Mic, MessageSquare, GraduationCap, BookOpen, Search, Mic2, Users, User } from 'lucide-react'

const useCases = [
  {
    icon: Mic,
    title: 'Journalists',
    description: 'Check claims during a press conference or interview without leaving the room.',
    features: ['Live briefings', 'Interview claims', 'Breaking coverage'],
  },
  {
    icon: MessageSquare,
    title: 'Reporters',
    description: 'Verify what is being said in the field while the conversation is still running.',
    features: ['Field reporting', 'Broadcast monitoring', 'On-location checks'],
  },
  {
    icon: GraduationCap,
    title: 'Students',
    description: 'Follow a lecture or debate and see which claims hold up, as they are made.',
    features: ['Lectures', 'Debates', 'Study sessions'],
  },
  {
    icon: BookOpen,
    title: 'Teachers',
    description: 'Model source-checking in the classroom by showing the evidence behind each claim.',
    features: ['Class discussion', 'Student talks', 'Media literacy'],
  },
  {
    icon: Search,
    title: 'Researchers',
    description: 'Check the factual claims inside a talk or recording you are reviewing.',
    features: ['Claim extraction', 'Source validation', 'Citation checks'],
  },
  {
    icon: Mic2,
    title: 'Speakers',
    description: 'Rehearse your own talk with the fact-checker running and fix what does not hold up.',
    features: ['Rehearsal', 'Self-review', 'Accuracy checks'],
  },
  {
    icon: Users,
    title: 'Interviewers',
    description: 'Have a live view of a guest\u2019s factual claims during a podcast or stream.',
    features: ['Podcasts', 'Live streams', 'Guest claims'],
  },
  {
    icon: User,
    title: 'Anyone',
    description: 'Check the claims in a conversation, stream or call you are part of.',
    features: ['Everyday claims', 'Calls and streams', 'Personal learning'],
  },
]

export function UseCases() {
  return (
    <section className="use-cases" id="use-cases" aria-labelledby="usecases-title">
      <div className="container">
        <motion.div
          className="section-header section-header--center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.5 }}
        >
          <span className="section-eyebrow">USE CASES</span>
          <h2 id="usecases-title" className="section-title">
            Built for conversations where facts matter.
          </h2>
          <p className="section-description">
            From newsrooms to classrooms, anywhere a claim is made out loud and the answer matters.
          </p>
        </motion.div>

        <div className="use-cases-grid" role="list">
          {useCases.map((useCase, index) => (
            <motion.article
              key={useCase.title}
              className="use-case-card"
              role="listitem"
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-100px' }}
              transition={{ duration: 0.5, delay: 0.1 + index * 0.06 }}
            >
              <div className="use-case-icon">
                <useCase.icon size={22} strokeWidth={1.8} aria-hidden="true" />
              </div>
              <h3 className="use-case-title">{useCase.title}</h3>
              <p className="use-case-description">{useCase.description}</p>
              <ul className="use-case-features">
                {useCase.features.map((feature) => (
                  <li key={feature}>{feature}</li>
                ))}
              </ul>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  )
}
