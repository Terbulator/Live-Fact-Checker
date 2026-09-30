import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Menu, X } from 'lucide-react'

const navLinks = [
  { id: 'how-it-works', label: 'How it works' },
  { id: 'demo', label: 'Demo' },
  { id: 'verdicts', label: 'Verdicts' },
  { id: 'use-cases', label: 'Use cases' },
  { id: 'technology', label: 'Technology' },
  { id: 'roadmap', label: 'Roadmap' },
]

export function Navigation() {
  const [scrolled, setScrolled] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20)
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  useEffect(() => {
    if (!mobileOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [mobileOpen])

  return (
    <motion.header
      className={`nav ${scrolled ? 'nav--scrolled' : ''}`}
      initial={{ y: -100, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.4, ease: [0.2, 0.7, 0.3, 1] }}
    >
      <div className="nav__inner">
        <Link to="/" className="nav__brand" aria-label="Live Fact-Checker home">
          <span className="nav__mark" aria-hidden="true" />
          <span className="nav__title">LIVE FACT-CHECKER</span>
        </Link>

        <nav className="nav__links" aria-label="Main">
          <ul className="nav__list">
            {navLinks.map((link) => (
              <li key={link.id}>
                <a href={`/#${link.id}`} className="nav__link">
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="nav__actions">
          <Link to="/login" className="button button--ghost nav__login">
            Log in
          </Link>
          <Link to="/dashboard" className="button button--primary nav__signup">
            Open app
          </Link>

          <button
            type="button"
            className="nav__mobile-toggle"
            onClick={() => setMobileOpen((current) => !current)}
            aria-expanded={mobileOpen}
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
            aria-controls="mobile-menu"
          >
            {mobileOpen ? <X size={24} strokeWidth={2.5} /> : <Menu size={24} strokeWidth={2.5} />}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            id="mobile-menu"
            className="nav__mobile-menu"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3, ease: [0.2, 0.7, 0.3, 1] }}
          >
            <ul className="nav__mobile-list">
              {navLinks.map((link) => (
                <li key={link.id}>
                  <a
                    href={`/#${link.id}`}
                    className="nav__mobile-link"
                    onClick={() => setMobileOpen(false)}
                  >
                    {link.label}
                  </a>
                </li>
              ))}
              <li className="nav__mobile-divider" />
              <li>
                <Link to="/login" className="nav__mobile-link" onClick={() => setMobileOpen(false)}>
                  Log in
                </Link>
              </li>
              <li>
                <Link
                  to="/dashboard"
                  className="button button--primary nav__mobile-cta"
                  onClick={() => setMobileOpen(false)}
                >
                  Open app
                </Link>
              </li>
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.header>
  )
}
