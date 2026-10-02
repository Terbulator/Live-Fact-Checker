import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { motion, useReducedMotion } from 'framer-motion'
import {
  ArrowRight,
  ArrowUpRight,
  AudioWaveform,
  Check,
  CircleAlert,
  Eye,
  EyeOff,
  Link2,
  Lock,
  Mail,
  MailCheck,
  ShieldCheck,
  Sparkles,
  User,
  Video,
} from 'lucide-react'

import { SignalPath } from '../components/auth/SignalPath'
import { AccentKey, accentClass } from '../components/landing/tone'
import { useAuth } from '../hooks/useAuth'
import { friendlyAuthError, type FriendlyAuthError } from '../lib/authErrors'
import {
  MIN_PASSWORD_LENGTH,
  confirmMatches,
  passwordIssues,
  reviewPassword,
} from '../lib/password'

/**
 * Create an account.
 *
 * A real signup against Supabase Auth. The name is written to Supabase's own
 * user metadata, the password goes to Supabase and nowhere else, and the branch
 * after a successful call is made on whether Supabase returned a session — see
 * `hooks/useAuth` for why that is the only honest way to know whether this
 * project has email confirmation switched on.
 *
 * Layout is the login page's three-column scene, reused rather than reinvented:
 * pitch on the left, the card in the centre, a compact capability rail on the
 * right, and everything but the card collapses first. The difference is the
 * ambient layer — `SignalPath` rather than `EnergyField`, because signup is
 * about a form becoming valid, and that is a circuit completing rather than a
 * current following a cursor.
 *
 * The six states the brief asks for are the six branches below. `submitting` is
 * a real state with its own label and its own disabled controls, so the form is
 * never a frozen-looking thing while a request is in flight, and a second click
 * cannot start a second account.
 */

const EASE = [0.2, 0.7, 0.3, 1] as const

/** Framer's entrance, or nothing at all when the reader asked for less motion. */
const rise = (reduceMotion: boolean | null) => (reduceMotion ? false : { opacity: 0, y: 14 })

/**
 * Deliberately permissive. Supabase is the authority on what it will accept —
 * a stricter client regex would reject addresses the server would have taken,
 * which is the wrong way for a form to be wrong. This only catches the cases
 * that are certainly a typo, such as a missing `@` or a missing domain.
 */
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

const FIELDS = ['name', 'email', 'password', 'confirm'] as const
type Field = (typeof FIELDS)[number]

const FEATURES: { icon: typeof Video; accent: AccentKey; title: string; body: string }[] = [
  {
    icon: AudioWaveform,
    accent: 'green',
    title: 'Real-time verification',
    body: 'Claims are checked as they are spoken, not after the conversation.',
  },
  {
    icon: ShieldCheck,
    accent: 'lavender',
    title: 'Evidence-backed answers',
    body: 'Every verdict arrives with its sources and a confidence score.',
  },
  {
    icon: Link2,
    accent: 'orange',
    title: 'Video + URL analysis',
    body: 'Send a video or a link and the claims come out already checked.',
  },
]

interface Errors {
  name?: string
  email?: string
  password?: string
  confirm?: string
}

type AuthPhase =
  | 'idle'
  | 'form_error'
  | 'submitting'
  | 'auth_error'
  | 'confirmation_required'
  | 'success'

/** How hard the signal pushes, by viewport. */
function qualityFor(width: number): number {
  if (width < 760) return 0.8
  if (width < 1200) return 0.9
  return 1
}

/** Validate one field. Shared by the blur handler and the submit gate. */
function validate(field: Field, name: string, email: string, password: string, confirm: string): string | undefined {
  const value = { name, email, password, confirm }[field]
  switch (field) {
    case 'name':
      return value.trim() === '' ? 'Enter your name.' : undefined
    case 'email': {
      const trimmed = value.trim()
      if (trimmed === '') return 'Enter your email address.'
      if (!EMAIL_PATTERN.test(trimmed)) return 'That does not look like an email address.'
      return undefined
    }
    case 'password': {
      const issues = passwordIssues(value)
      return issues.length > 0 ? issues[0] : undefined
    }
    case 'confirm': {
      if (value === '') return 'Repeat your password.'
      if (value !== password && !confirmMatches(password, value)) {
        return 'These passwords do not match.'
      }
      return undefined
    }
  }
}

export function SignupPage() {
  const { status, configured, signUp } = useAuth()
  const navigate = useNavigate()
  const reduceMotion = useReducedMotion()

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')

  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [touched, setTouched] = useState<Partial<Record<Field, boolean>>>({})
  const [phase, setPhase] = useState<AuthPhase>('idle')
  const [authError, setAuthError] = useState<FriendlyAuthError | null>(null)
  const [sentTo, setSentTo] = useState<string | null>(null)

  const [quality, setQuality] = useState(1)
  const [focusY, setFocusY] = useState<number | null>(null)
  const [focused, setFocused] = useState(false)
  const [sweepToken, setSweepToken] = useState(0)
  const [pulse, setPulse] = useState(false)

  const formRef = useRef<HTMLFormElement | null>(null)
  const wasValid = useRef(false)

  const values = useMemo(() => ({ name, email, password, confirm }), [name, email, password, confirm])

  const allErrors = useMemo<Errors>(() => {
    const next: Errors = {}
    for (const field of FIELDS) {
      const problem = validate(field, values.name, values.email, values.password, values.confirm)
      if (problem !== undefined) next[field] = problem
    }
    return next
  }, [values])

  const isValid = Object.keys(allErrors).length === 0

  /**
   * Validation becoming true completes the route once. This is the form telling
   * the animation something true rather than the animation being told to react.
   */
  useEffect(() => {
    if (isValid && !wasValid.current) {
      wasValid.current = true
      setSweepToken((token) => token + 1)
    } else if (!isValid) {
      wasValid.current = false
    }
  }, [isValid])

  useEffect(() => {
    const read = () => setQuality(qualityFor(window.innerWidth))
    read()
    window.addEventListener('resize', read)
    return () => window.removeEventListener('resize', read)
  }, [])

  /**
   * On a successful signup with confirmation off there is nothing to show: the
   * reader is already signed in and the fact-checker is the next thing they
   * want. A short success beat gives the signal its pulse, then moves on.
   */
  useEffect(() => {
    if (phase !== 'success') return undefined
    const wait = reduceMotion ? 0 : 850
    const timer = window.setTimeout(() => navigate('/dashboard', { replace: true }), wait)
    return () => window.clearTimeout(timer)
  }, [phase, navigate, reduceMotion])

  /**
   * Which node on the signal reacts. The card is centred, so the focus point is
   * the field's own vertical centre against the viewport's horizontal centre.
   */
  const handleFocus = useCallback((event: React.FocusEvent<HTMLInputElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    setFocusY(box.top + box.height / 2)
    setFocused(true)
  }, [])

  const handleBlur = useCallback(
    (field: Field) => () => {
      setTouched((current) => ({ ...current, [field]: true }))
      setFocused(false)
    },
    [],
  )

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    // A second click while a request is in flight must not start a second
    // account, whatever the button state managed to do.
    if (phase === 'submitting') return

    setTouched({ name: true, email: true, password: true, confirm: true })

    const current: Errors = {}
    for (const field of FIELDS) {
      const problem = validate(field, name, email, password, confirm)
      if (problem !== undefined) current[field] = problem
    }
    if (Object.keys(current).length > 0) {
      setPhase('form_error')
      setAuthError(null)
      // Send focus to the first thing that needs fixing, rather than making the
      // reader hunt for it.
      const first = FIELDS.find((field) => current[field] !== undefined)
      const input = first === undefined ? null : formRef.current?.querySelector<HTMLInputElement>(`#signup-${first}`)
      input?.focus()
      return
    }

    setPhase('submitting')
    setAuthError(null)
    try {
      const outcome = await signUp({
        name: name.trim(),
        email: email.trim(),
        password,
      })
      if (outcome.kind === 'signed_in') {
        setPhase('success')
        setPulse(true)
      } else {
        // The account exists but is not usable yet. Say exactly that, and do
        // not pretend the reader is signed in.
        setSentTo(outcome.email)
        setPhase('confirmation_required')
        setPulse(true)
      }
    } catch (error) {
      setAuthError(friendlyAuthError(error))
      setPhase('auth_error')
      // The password is dropped the moment the request resolves, successfully
      // or not, so it never sits in state longer than it has to.
    } finally {
      setPassword('')
      setConfirm('')
    }
  }

  // A reader who is already signed in has no use for this form.
  if (status === 'authenticated') return <Navigate to="/dashboard" replace />

  const submitting = phase === 'submitting'
  const showFieldError = (field: Field): string | undefined =>
    touched[field] === true ? allErrors[field] : undefined

  const review = reviewPassword(password)
  const confirmState =
    confirm === '' ? 'idle' : confirm === password || confirmMatches(password, confirm) ? 'match' : 'mismatch'

  return (
    <div className="lfp-root lfp-bg--black lfp-auth">
      <SignalPath
        quality={quality}
        focusY={focusY}
        focused={focused}
        sweepToken={sweepToken}
        pulse={pulse}
      />

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
            Start
            <br />
            <span className="lfp-auth__headlineAccent">verifying</span>
            <br />
            in seconds.
          </h1>

          <p className="lfp-auth__lede">
            One account keeps every conversation, transcript and verdict you produce in one place.
          </p>

          <div className="lfp-auth__live">
            <span className="lfp-auth__liveIcon" aria-hidden="true">
              <Sparkles size={17} />
            </span>
            <div>
              <strong>Free while in preview</strong>
              <p>The fact-checker itself needs no account.</p>
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

          {phase === 'confirmation_required' ? (
            <ConfirmationPending email={sentTo} />
          ) : (
            <>
              <h2 className="lfp-auth__title">Create your account</h2>
              <p className="lfp-auth__sub">
                Create your account to keep your fact-checking sessions together.
              </p>

              {!configured && (
                <div className="lfp-auth__notice lfp-auth__notice--warn" role="status">
                  <CircleAlert className="lfp-auth__noticeIcon" size={16} aria-hidden="true" />
                  <div>
                    <strong>Signup is not configured on this deployment.</strong>
                    <p>
                      No Supabase project is set, so no account can be created here. The
                      fact-checker is still open and needs no account.
                    </p>
                  </div>
                </div>
              )}

              {/*
                Status only. The visible error panel below is its own live
                region (`role="alert"`), so putting the failure text here as
                well would announce it twice — once assertively and once
                politely — for a reader using a screen reader.
              */}
              <p className="sr-only" role="status" aria-live="polite">
                {submitting ? 'Creating your account.' : ''}
              </p>

              {authError !== null && (
                <div className="lfp-auth__notice lfp-auth__notice--error" role="alert">
                  <CircleAlert className="lfp-auth__noticeIcon" size={16} aria-hidden="true" />
                  <div>
                    <strong>{authError.title}</strong>
                    <p>{authError.message}</p>
                  </div>
                </div>
              )}

              <form
                className="lfp-auth__form"
                ref={formRef}
                onSubmit={(event) => void onSubmit(event)}
                noValidate
              >
                <Field
                  id="signup-name"
                  name="name"
                  label="Full name"
                  icon={User}
                  type="text"
                  autoComplete="name"
                  placeholder="Ada Lovelace"
                  value={name}
                  error={showFieldError('name')}
                  onChange={setName}
                  onFocus={handleFocus}
                  onBlur={handleBlur('name')}
                  disabled={submitting}
                />

                <Field
                  id="signup-email"
                  name="email"
                  label="Email address"
                  icon={Mail}
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  value={email}
                  error={showFieldError('email')}
                  onChange={setEmail}
                  onFocus={handleFocus}
                  onBlur={handleBlur('email')}
                  disabled={submitting}
                />

                <div className="lfp-auth__field">
                  <label htmlFor="signup-password" className="lfp-auth__label">
                    Password
                  </label>
                  <div
                    className={`lfp-auth__control${
                      showFieldError('password') === undefined && touched.password === true
                        ? ' lfp-auth__control--valid'
                        : ''
                    }`}
                  >
                    <Lock className="lfp-auth__icon" size={16} aria-hidden="true" />
                    <input
                      type={showPassword ? 'text' : 'password'}
                      id="signup-password"
                      name="password"
                      className="lfp-auth__input"
                      placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
                      autoComplete="new-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      onFocus={handleFocus}
                      onBlur={handleBlur('password')}
                      disabled={submitting}
                      aria-invalid={showFieldError('password') !== undefined}
                      // Points at whichever is currently true: the failure if
                      // there is one, otherwise the meter that is explaining the
                      // strength. Never both, so the field is not described twice.
                      aria-describedby={
                        showFieldError('password') !== undefined
                          ? 'signup-password-error'
                          : password === ''
                            ? undefined
                            : 'signup-password-help'
                      }
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

                  {/*
                    The meter reports the rules that were actually applied. No
                    score, no entropy claim: four things the reader can act on,
                    each also in text, so the state survives a monochrome screen.
                  */}
                  {password !== '' && (
                    <div className="lfp-signup__meter" id="signup-password-help">
                      <div
                        className="lfp-signup__meterBars"
                        role="meter"
                        aria-valuemin={0}
                        aria-valuemax={3}
                        aria-valuenow={review.level}
                        aria-valuetext={review.checks
                          .filter((check) => check.met)
                          .map((check) => check.label)
                          .join(', ')}
                      >
                        {[1, 2, 3].map((step) => (
                          <span
                            key={step}
                            className={`lfp-signup__meterBar${
                              review.level >= step ? ' lfp-signup__meterBar--on' : ''
                            }`}
                            data-level={step}
                          />
                        ))}
                      </div>
                      <ul className="lfp-signup__rules">
                        {review.checks.map((check) => (
                          <li
                            key={check.label}
                            className={`lfp-signup__rule${check.met ? ' lfp-signup__rule--met' : ''}`}
                          >
                            <Check
                              className="lfp-signup__ruleTick"
                              size={12}
                              aria-hidden="true"
                            />
                            {check.label}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {showFieldError('password') !== undefined && (
                    <p className="lfp-signup__error" id="signup-password-error">
                      <CircleAlert size={13} aria-hidden="true" />
                      {showFieldError('password')}
                    </p>
                  )}
                </div>

                <div className="lfp-auth__field">
                  <label htmlFor="signup-confirm" className="lfp-auth__label">
                    Confirm password
                  </label>
                  <div
                    className={`lfp-auth__control lfp-signup__confirm--${confirmState}`}
                  >
                    <Lock className="lfp-auth__icon" size={16} aria-hidden="true" />
                    <input
                      type={showConfirm ? 'text' : 'password'}
                      id="signup-confirm"
                      name="confirm"
                      className="lfp-auth__input"
                      placeholder="Repeat your password"
                      autoComplete="new-password"
                      value={confirm}
                      onChange={(event) => setConfirm(event.target.value)}
                      onFocus={handleFocus}
                      onBlur={handleBlur('confirm')}
                      disabled={submitting}
                      aria-invalid={showFieldError('confirm') !== undefined}
                      aria-describedby="signup-confirm-help"
                    />
                    {/*
                      A tick, not just a green border: a match has to be
                      legible without colour.
                    */}
                    {confirmState === 'match' && (
                      <Check className="lfp-signup__confirmTick" size={17} aria-hidden="true" />
                    )}
                    <button
                      type="button"
                      className="lfp-auth__reveal"
                      onClick={() => setShowConfirm((current) => !current)}
                      aria-label={showConfirm ? 'Hide confirm password' : 'Show confirm password'}
                      aria-pressed={showConfirm}
                      disabled={submitting}
                    >
                      {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                  {/*
                    One live region carries the whole story for this field: a
                    success note when it matches, the reason when it does not.
                    An empty confirmation is a failure too, not just a mismatch,
                    so it gets the same treatment as any other field rather than
                    being silently ignored. The id referenced by
                    aria-describedby always exists, so the association never
                    dangles — only the text inside changes.
                  */}
                  <p
                    className={`lfp-signup__hint${
                      confirmState === 'match' ? ' lfp-signup__hint--good' : ''
                    }${confirmState === 'mismatch' || showFieldError('confirm') !== undefined
                      ? ' lfp-signup__hint--bad'
                      : ''}`}
                    id="signup-confirm-help"
                    aria-live="polite"
                  >
                    {confirmState === 'match'
                      ? 'Passwords match.'
                      : (showFieldError('confirm') ?? '')}
                  </p>
                </div>

                <button
                  type="submit"
                  className={`lfp-btn lfp-btn--accent lfp-auth__submit${
                    phase === 'success' ? ' lfp-auth__submit--done' : ''
                  }`}
                  disabled={submitting || phase === 'success' || !configured}
                  aria-busy={submitting}
                >
                  {phase === 'success' ? (
                    <>
                      <Check size={17} aria-hidden="true" />
                      Account created
                    </>
                  ) : (
                    <>
                      {submitting && (
                        <span className="lfp-signup__spinner" aria-hidden="true" />
                      )}
                      {submitting ? 'Creating account…' : 'Create account'}
                      {!submitting && <ArrowRight size={17} aria-hidden="true" />}
                    </>
                  )}
                </button>
              </form>

              <p className="lfp-auth__footer">
                Already have an account?{' '}
                <Link to="/login" className="lfp-auth__link">
                  Log in
                  <ArrowUpRight size={14} aria-hidden="true" />
                </Link>
              </p>
            </>
          )}
        </motion.div>

        <motion.aside
          className="lfp-auth__stack lfp-auth__stack--compact"
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

/**
 * One field, and the error it owns.
 *
 * The message is wired with `aria-describedby` and the state with
 * `aria-invalid`, so the failure is announced and not only coloured. Errors are
 * rendered in text with an icon, never as a border colour alone.
 */
function Field({
  id,
  name,
  label,
  icon: Icon,
  type,
  autoComplete,
  placeholder,
  value,
  error,
  onChange,
  onFocus,
  onBlur,
  disabled,
}: {
  id: string
  name: string
  label: string
  icon: typeof User
  type: string
  autoComplete: string
  placeholder: string
  value: string
  error: string | undefined
  onChange: (value: string) => void
  onFocus: (event: React.FocusEvent<HTMLInputElement>) => void
  onBlur: () => void
  disabled: boolean
}) {
  const errorId = `${id}-error`
  return (
    <div className="lfp-auth__field">
      <label htmlFor={id} className="lfp-auth__label">
        {label}
      </label>
      <div className={`lfp-auth__control${error === undefined ? '' : ' lfp-auth__control--error'}`}>
        <Icon className="lfp-auth__icon" size={16} aria-hidden="true" />
        <input
          type={type}
          id={id}
          name={name}
          className="lfp-auth__input"
          placeholder={placeholder}
          autoComplete={autoComplete}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onFocus={onFocus}
          onBlur={onBlur}
          disabled={disabled}
          aria-invalid={error !== undefined}
          aria-describedby={error === undefined ? undefined : errorId}
        />
      </div>
      {error !== undefined && (
        <p className="lfp-signup__error" id={errorId}>
          <CircleAlert size={13} aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * Email confirmation is on for this project, so the account exists but is not
 * usable yet. This says precisely that: the address to look at, what will
 * arrive, and where to go once it has.
 */
function ConfirmationPending({ email }: { email: string | null }) {
  return (
    <div className="lfp-signup__confirmState">
      <span className="lfp-signup__confirmIcon" aria-hidden="true">
        <MailCheck size={22} />
      </span>

      <h2 className="lfp-auth__title">Check your email</h2>
      <p className="lfp-auth__sub">
        Your account is created. Confirm your address to finish setting it up
        {email === null ? '.' : (
          <>
            {' '} — we sent a link to <strong>{email}</strong>.
          </>
        )}
      </p>

      <ol className="lfp-signup__steps">
        <li>Open the confirmation email.</li>
        <li>Follow the link to finish signing in.</li>
        <li>You will land straight in the fact-checker.</li>
      </ol>

      <p className="lfp-auth__footer lfp-signup__confirmFooter">
        Already confirmed?{' '}
        <Link to="/login" className="lfp-auth__link">
          Log in
          <ArrowUpRight size={14} aria-hidden="true" />
        </Link>
      </p>
    </div>
  )
}
