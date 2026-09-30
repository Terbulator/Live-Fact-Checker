import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'

const productLinks = [
  { label: 'How it works', href: '/#how-it-works' },
  { label: 'Verdicts', href: '/#verdicts' },
  { label: 'Use cases', href: '/#use-cases' },
  { label: 'Technology', href: '/#technology' },
  { label: 'Roadmap', href: '/#roadmap' },
]

const appLinks = [
  { label: 'Open the app', href: '/dashboard' },
  { label: 'Log in', href: '/login' },
  { label: 'Sign up', href: '/signup' },
]

export function Footer() {
  return (
    <footer className="footer" role="contentinfo">
      <div className="container">
        <motion.div
          className="footer-grid"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
        >
          <div className="footer-brand">
            <Link to="/" className="footer-logo" aria-label="Live Fact-Checker home">
              <span className="footer-logo-mark" aria-hidden="true" />
              <span>LIVE FACT-CHECKER</span>
            </Link>
            <p className="footer-tagline">
              Real-time fact verification for live conversations. No preloaded fact database.
            </p>
          </div>

          <nav className="footer-nav" aria-label="Product">
            <h4 className="footer-nav-title">Product</h4>
            <ul>
              {productLinks.map((link) => (
                <li key={link.href}>
                  <a href={link.href} className="footer-link">
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>

          <nav className="footer-nav" aria-label="Application">
            <h4 className="footer-nav-title">Application</h4>
            <ul>
              {appLinks.map((link) => (
                <li key={link.href}>
                  <Link to={link.href} className="footer-link">
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </motion.div>

        <motion.div
          className="footer-bottom"
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.3 }}
        >
          <p className="footer-copyright">
            &copy; {new Date().getFullYear()} Live Fact-Checker
          </p>
          <p className="footer-note">Live evidence for live claims.</p>
        </motion.div>
      </div>
    </footer>
  )
}
