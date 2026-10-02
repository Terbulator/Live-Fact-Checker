import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Menu, X } from 'lucide-react'

/**
 * Sticky marketing navigation.
 *
 * The page alternates light and dark bands, so a single fixed nav colour would
 * fight whatever it was floating over. This watches which section is currently
 * behind the bar and flips the nav to match: translucent white over a light
 * band, translucent near-black over a dark one.
 *
 * "Start for Free" and "Log in" are plain links into the existing routes. No
 * authentication is faked: /login and /signup already state that accounts are
 * not implemented.
 */
const LINKS = [
  { label: 'Product', href: '#product' },
  { label: 'How it works', href: '#pipeline' },
  { label: 'Sources', href: '#sources' },
  { label: 'Features', href: '#capabilities' },
]

export function Navigation() {
  const [open, setOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [overDark, setOverDark] = useState(false)

  useEffect(() => {
    const sections = Array.from(
      document.querySelectorAll<HTMLElement>('[class*="lfp-bg--"], .lfp-cta, .lfp-footer, .lfp-hero'),
    )

    const update = () => {
      setScrolled(window.scrollY > 12)
      // The bar is 68px tall; the section crossing that line decides the theme.
      const probe = window.scrollY + 80
      let current: HTMLElement | null = null
      for (const section of sections) {
        if (section.offsetTop <= probe) current = section
      }
      setOverDark(
        Boolean(
          current?.className.match(/lfp-bg--(night|charcoal|black)/) ||
            current?.classList.contains('lfp-cta') ||
            current?.classList.contains('lfp-footer'),
        ),
      )
    }

    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [])

  // A resize back to desktop should not leave the mobile sheet open behind.
  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth > 900) setOpen(false)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const classes = [
    'lfp-nav',
    scrolled ? 'lfp-nav--solid' : '',
    overDark ? 'lfp-nav--over-dark' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <header className={classes}>
      <div className="lfp-container lfp-nav__inner">
        <Link to="/" className="lfp-brand" onClick={() => setOpen(false)}>
          <span className="lfp-brand__mark" aria-hidden="true" />
          LIVE FACT CHECKER
        </Link>

        <nav className="lfp-nav__links" aria-label="Primary">
          {LINKS.map((link) => (
            <a key={link.href} href={link.href} className="lfp-nav__link">
              {link.label}
            </a>
          ))}
        </nav>

        <div className="lfp-nav__actions">
          <Link to="/login" className="lfp-btn lfp-btn--ghost lfp-btn--sm">
            Log in
          </Link>
          <Link to="/dashboard" className="lfp-btn lfp-btn--primary lfp-btn--invert lfp-btn--sm">
            Start for Free
          </Link>
        </div>

        <button
          type="button"
          className="lfp-nav__toggle"
          aria-expanded={open}
          aria-controls="lfp-mobile-nav"
          aria-label={open ? 'Close menu' : 'Open menu'}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {open ? (
        <div id="lfp-mobile-nav" className="lfp-nav__sheet">
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="lfp-nav__sheetLink"
              onClick={() => setOpen(false)}
            >
              {link.label}
            </a>
          ))}
          <Link
            to="/login"
            className="lfp-btn lfp-btn--ghost"
            onClick={() => setOpen(false)}
          >
            Log in
          </Link>
          <Link
            to="/dashboard"
            className="lfp-btn lfp-btn--primary lfp-btn--invert"
            onClick={() => setOpen(false)}
          >
            Start for Free
          </Link>
        </div>
      ) : null}
    </header>
  )
}
