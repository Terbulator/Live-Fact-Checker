import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { motion, useReducedMotion } from 'framer-motion'
import {
  ArrowRight,
  ArrowUpRight,
  AudioWaveform,
  CircleAlert,
  Eye,
  EyeOff,
  Link2,
  Lock,
  Mail,
  ScrollText,
  ShieldCheck,
  Video,
} from 'lucide-react'

import { EnergyField } from '../components/auth/EnergyField'
import { AccentKey, accentClass } from '../components/landing/tone'
import { useAuth } from '../hooks/useAuth'
import { friendlyAuthError, type FriendlyAuthError } from '../lib/authErrors'

/**
 * Sign in.
 *
 * A real password sign-in against Supabase Auth, through the same client, the
 * same provider and the same error vocabulary as `/signup`. There is one auth
 * system in this app and this page is part of it.
 *
 * The ambient layer stays `EnergyField` — signup has its own, because creating
 * an account is a different moment from returning to one. The composition is
 * shared: pitch on the left, the card in the centre, the capability stack on the
 * right, everything but the card collapsing first.
 *
 * The password never leaves this component. It is held in state while it is
 * typed, handed straight to Supabase, and cleared the moment the request
 * resolves — never logged, never stored, never in a URL.
 */

const EASE = [0.2, 0.7, 0.3, 1] as const

/** Framer's entrance, or nothing at all when the reader asked for less motion. */
const rise = (reduceMotion: boolean | null) => (reduceMotion ? false : { opacity: 0, y: 14 })

const FEATURES: { icon: typeof Video; accent: AccentKey; title: string; body: string }[] = [
  {
    icon: Video,
    accent: 'orange',
    title: 'Video analysis',
    body: 'Extract and verify claims from any video.',
  },
  {
    icon: Link2,
    accent: 'blue',
    title: 'URL verification',
    body: 'Check claims from YouTube and the web.',
  },
  {
    icon: ScrollText,
    accent: 'lavender',
    title: 'Source-backed evidence',
    body: 'Get reliable sources with confidence scores.',
  },
]

/**
 * How hard the energy field pushes, by viewport. The mote budget is already
 * area-scaled, so this only trims a little: cutting it hard made the field
 * nearly invisible behind a card that fills a phone screen. The floor is kept
 * above 0.75 because that is the threshold at which the field drops its widest
 * two ribbon layers, and a phone needs all of them to read as flowing.
 */
function qualityFor(width: number): number {
  if (width < 760) return 0.78
  if (width < 1200) return 0.88
  return 1
}

export function LoginPage() {
  const { status, configured, signIn } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [quality, setQuality] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<FriendlyAuthError | null>(null)

  const reduceMotion = useReducedMotion()

  useEffect(() => {
    const read = () => setQuality(qualityFor(window.innerWidth))
    read()
    window.addEventListener('resize', read)
    return () => window.removeEventListener('resize', read)
  }, [])

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitting) return

    setSubmitting(true)
    setError(null)
    try {
      await signIn(email.trim(), password)
      navigate('/dashboard', { replace: true })
    } catch (thrown) {
      setError(friendlyAuthError(thrown))
    } finally {
      setSubmitting(false)
      setPassword('')
    }
  }

  if (status === 'authenticated') return <Navigate to="/dashboard" replace />

  return (
    <div className="lfp-root lfp-bg--black lfp-auth">
      <EnergyField quality={quality} />

      <header className="lfp-auth__chrome lfp-auth__chrome--top">
        <Link to="/" className="lfp-brand lfp-auth__brand" aria-label="Live Fact Checker home">
          <span className="lfp-brand__mark" aria-hidden="true" />
          LIVE FACT CHECKER
        </Link>

        <p className="lfp-auth__secure">
          <ShieldCheck size={15} aria-hidden="true" />
          Secure &amp; Private
        </p>
      </header>

      <main className="lfp-auth__scene">
        <motion.aside
          className="lfp-auth__pitch"
          initial={rise(reduceMotion)}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE }}
        >
          <p className="lfp-eyebrow lfp-auth__eyebrow">Real-time &bull; AI-powered &bull; Source-backed</p>

          <h1 className="lfp-auth__headline">
            Truth
            <br />
            <span className="lfp-auth__headlineAccent">moves</span>
            <br />
            with you.
          </h1>

          <p className="lfp-auth__lede">
            Sign in to verify claims from conversations, videos and the web.
          </p>

          <div className="lfp-auth__live">
            <span className="lfp-auth__liveIcon" aria-hidden="true">
              <AudioWaveform size={17} />
            </span>
            <div>
              <strong>Live fact checking</strong>
              <p>Verify claims as they happen.</p>
            </div>
          </div>
        </motion.aside>

        <motion.div
          className="lfp-auth__card"
          initial={rise(reduceMotion)}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.62, delay: 0.06, ease: EASE }}
        >
          <div className="lfp-auth__cardBrand">
            <span className="lfp-brand__mark" aria-hidden="true" />
            LIVE FACT CHECKER
          </div>

          <h2 className="lfp-auth__title">Welcome back</h2>
          <p className="lfp-auth__sub">Sign in to continue fact-checking claims in real time.</p>

          {!configured && (
            <div className="lfp-auth__notice lfp-auth__notice--warn" role="status">
              <CircleAlert className="lfp-auth__noticeIcon" size={16} aria-hidden="true" />
              <div>
                <strong>Accounts are not configured on this deployment.</strong>
                <p>
                  No Supabase project is set, so there is nothing to sign in to. The
                  fact-checker is open and needs no account.
                </p>
              </div>
            </div>
          )}

          {/* Status only. The failure panel is its own `role="alert"`, so
              repeating the message here would announce it twice. */}
          <p className="sr-only" role="status" aria-live="polite">
            {submitting ? 'Signing you in.' : ''}
          </p>

          {error !== null && (
            <div className="lfp-auth__notice lfp-auth__notice--error" role="alert">
              <CircleAlert className="lfp-auth__noticeIcon" size={16} aria-hidden="true" />
              <div>
                <strong>{error.title}</strong>
                <p>{error.message}</p>
              </div>
            </div>
          )}

          <form className="lfp-auth__form" onSubmit={(event) => void onSubmit(event)} noValidate>
            <div className="lfp-auth__field">
              <label htmlFor="login-email" className="lfp-auth__label">
                Email address
              </label>
              <div className="lfp-auth__control">
                <Mail className="lfp-auth__icon" size={16} aria-hidden="true" />
                <input
                  type="email"
                  id="login-email"
                  name="email"
                  className="lfp-auth__input"
                  placeholder="you@example.com"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  disabled={submitting}
                />
              </div>
            </div>

            <div className="lfp-auth__field">
              <label htmlFor="login-password" className="lfp-auth__label">
                Password
              </label>
              <div className="lfp-auth__control">
                <Lock className="lfp-auth__icon" size={16} aria-hidden="true" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  id="login-password"
                  name="password"
                  className="lfp-auth__input"
                  placeholder="••••••••"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={submitting}
                />
                <button
                  type="button"
                  className="lfp-auth__reveal"
                  onClick={() => setShowPassword((current) => !current)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                  disabled={submitting}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              className="lfp-btn lfp-btn--accent lfp-auth__submit"
              disabled={submitting || !configured}
              aria-busy={submitting}
            >
              {submitting ? 'Signing in…' : 'Sign in'}
              {!submitting && <ArrowRight size={17} aria-hidden="true" />}
            </button>
          </form>

          <p className="lfp-auth__footer">
            Don&apos;t have an account?{' '}
            <Link to="/signup" className="lfp-auth__link">
              Create account
              <ArrowUpRight size={14} aria-hidden="true" />
            </Link>
          </p>
        </motion.div>

        <motion.aside
          className="lfp-auth__stack"
          aria-label="Product capabilities"
          initial={rise(reduceMotion)}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.12, ease: EASE }}
        >
          {FEATURES.map(({ icon: Icon, accent, title, body }) => (
            <article key={title} className={`lfp-auth__feature ${accentClass(accent)}`}>
              <span className="lfp-auth__featureIcon" aria-hidden="true">
                <Icon size={16} />
              </span>
              <div>
                <h3>{title}</h3>
                <p>{body}</p>
              </div>
            </article>
          ))}
        </motion.aside>
      </main>

      <footer className="lfp-auth__chrome lfp-auth__chrome--bottom">
        <p>© 2026 Live Fact Checker</p>
        <nav aria-label="Site">
          <Link to="/">Back to site</Link>
          <Link to="/dashboard">Open the fact-checker</Link>
          <span aria-disabled="true">Privacy</span>
          <span aria-disabled="true">Terms</span>
        </nav>
      </footer>
    </div>
  )
}
