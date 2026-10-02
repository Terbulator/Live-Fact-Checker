/**
 * Signup behaviour.
 *
 * This is the real flow, tested at the client boundary: a validation pass, a
 * call to Supabase's `signUp`, and the branch that follows it. Nothing here
 * touches a real project or a real account — the auth provider is stubbed and
 * the outcomes it can return are the two that matter, which are decided by
 * whether Supabase handed back a session.
 *
 * The two outcomes are the heart of the file:
 *
 *   session returned    -> confirmation is off, the reader is signed in, and
 *                          the page goes to the fact-checker
 *   no session          -> confirmation is on, an account exists but is not
 *                          usable, and the page must say so instead of implying
 *                          the reader is signed in
 *
 * The second is the case that is easy to get wrong and dishonest to fudge, so
 * it gets the most attention.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { SignupPage } from './SignupPage'
import { MIN_PASSWORD_LENGTH } from '../lib/password'

const signUp = vi.fn()

const authState = {
  status: 'anonymous' as string,
  user: null as unknown,
  configured: true,
}

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    ...authState,
    ready: true,
    signUp,
    signIn: vi.fn(),
    signOut: vi.fn(),
  }),
  displayName: () => 'Guest',
}))

function renderSignup() {
  return render(
    <MemoryRouter initialEntries={['/signup']}>
      <Routes>
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/login" element={<h1>Log in</h1>} />
        <Route path="/dashboard" element={<h1>Fact-checker</h1>} />
      </Routes>
    </MemoryRouter>,
  )
}

const GOOD_PASSWORD = 'Tr0ub4dor-and-3'

function fillValidForm(overrides: Partial<Record<string, string>> = {}) {
  const values = {
    'Full name': 'Ada Lovelace',
    'Email address': 'ada@example.com',
    Password: GOOD_PASSWORD,
    'Confirm password': GOOD_PASSWORD,
    ...overrides,
  }
  for (const [label, value] of Object.entries(values)) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } })
  }
}

function submit() {
  fireEvent.click(screen.getByRole('button', { name: /^create account$/i }))
}

/** Confirmation on: an account exists, no session. */
function confirmationRequired() {
  return { kind: 'confirmation_required', email: 'ada@example.com' }
}

/** Confirmation off: signed in immediately. */
function signedIn() {
  return { kind: 'signed_in' }
}

beforeEach(() => {
  signUp.mockReset()
  authState.status = 'anonymous'
  authState.user = null
  authState.configured = true
  signUp.mockResolvedValue(confirmationRequired())
})

describe('SignupPage', () => {
  it('renders the card the brief describes', () => {
    renderSignup()

    expect(screen.getByRole('link', { name: /live fact checker home/i })).toHaveAttribute('href', '/')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/start\s*verifying/i)
    expect(screen.getByRole('heading', { name: /create your account/i })).toBeInTheDocument()
    expect(
      screen.getByText(/keep your fact-checking sessions together/i),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^create account$/i })).toBeInTheDocument()
  })

  it('lists the three capabilities as headings', () => {
    renderSignup()

    expect(screen.getByRole('heading', { name: /real-time verification/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /evidence-backed answers/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /video \+ url analysis/i })).toBeInTheDocument()
  })

  it('marks the signal decorative so it is never announced', () => {
    const { container } = renderSignup()

    expect(container.querySelector('.lfp-auth__signal')).toHaveAttribute('aria-hidden', 'true')
  })

  it('gives every field the right autocomplete token', () => {
    renderSignup()

    expect(screen.getByLabelText('Full name')).toHaveAttribute('autocomplete', 'name')
    expect(screen.getByLabelText('Email address')).toHaveAttribute('autocomplete', 'email')
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password')
    expect(screen.getByLabelText('Confirm password')).toHaveAttribute('autocomplete', 'new-password')
  })

  // ------------------------------------------------------------ validation

  it('refuses to submit an empty form and says what is missing', async () => {
    renderSignup()
    submit()

    await waitFor(() => expect(screen.getByText(/enter your name/i)).toBeInTheDocument())
    expect(screen.getByText(/enter your email address/i)).toBeInTheDocument()
    expect(screen.getByText(/enter a password/i)).toBeInTheDocument()
    expect(screen.getByText(/repeat your password/i)).toBeInTheDocument()
    expect(signUp).not.toHaveBeenCalled()
  })

  it('rejects an email address that is plainly a typo', async () => {
    renderSignup()
    fillValidForm({ 'Email address': 'ada@example' })
    submit()

    expect(await screen.findByText(/does not look like an email/i)).toBeInTheDocument()
    expect(signUp).not.toHaveBeenCalled()
  })

  it('rejects a password below the minimum, and names the minimum', async () => {
    renderSignup()
    fillValidForm({ Password: 'aA1!aaa', 'Confirm password': 'aA1!aaa' })
    submit()

    await waitFor(() => expect(signUp).not.toHaveBeenCalled())
    // The field points at this message, so this is what a screen reader reads.
    const message = document.getElementById('signup-password-error')
    expect(message).toHaveTextContent(new RegExp(`at least ${MIN_PASSWORD_LENGTH} characters`, 'i'))
    expect(signUp).not.toHaveBeenCalled()
  })

  it('rejects a confirmation that does not match', async () => {
    renderSignup()
    fillValidForm({ 'Confirm password': 'something-else-entirely' })
    submit()

    expect(await screen.findByText(/do not match/i)).toBeInTheDocument()
    expect(signUp).not.toHaveBeenCalled()
  })

  it('marks a matching confirmation in text, not only in colour', async () => {
    renderSignup()
    fillValidForm()

    expect(await screen.findByText(/passwords match/i)).toBeInTheDocument()
  })

  it('marks the password strength with the rules that were actually applied', async () => {
    renderSignup()
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'aaaaaaaa' } })

    const meter = await screen.findByRole('meter')
    // Four named rules, so the reader can act on a specific one.
    expect(screen.getByText(/upper and lower case/i)).toBeInTheDocument()
    expect(screen.getByText(/a number/i)).toBeInTheDocument()
    expect(screen.getByText(/a symbol/i)).toBeInTheDocument()
    // Length is met, so exactly one bar is lit.
    expect(meter).toHaveAttribute('aria-valuenow', '1')
  })

  it('does not shout about validation before a field has been visited', () => {
    renderSignup()

    expect(screen.queryByText(/enter your name/i)).not.toBeInTheDocument()
  })

  it('exposes a11y state rather than relying on the border colour', async () => {
    renderSignup()
    fillValidForm({ 'Email address': 'nope' })
    submit()

    const email = screen.getByLabelText('Email address')
    await waitFor(() => expect(email).toHaveAttribute('aria-invalid', 'true'))
    const describedBy = email.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    // The id it points at really exists and really holds the message.
    expect(document.getElementById(describedBy as string)).toHaveTextContent(
      /does not look like an email/i,
    )
  })

  // ------------------------------------------------------------- submitting

  it('shows a submitting state and cannot be submitted twice', async () => {
    let release: (() => void) | undefined
    signUp.mockImplementation(() => new Promise((resolve) => { release = resolve }))
    renderSignup()
    fillValidForm()

    submit()

    const button = await screen.findByRole('button', { name: /creating account/i })
    await waitFor(() => expect(button).toBeDisabled())
    expect(button).toHaveAttribute('aria-busy', 'true')
    fireEvent.click(button)
    expect(signUp).toHaveBeenCalledTimes(1)

    release?.()
  })

  it('hands Supabase the name as user metadata and the email trimmed', async () => {
    renderSignup()
    fillValidForm({ 'Full name': '  Ada Lovelace  ', 'Email address': ' ada@example.com ' })
    submit()

    await waitFor(() =>
      expect(signUp).toHaveBeenCalledWith({
        name: 'Ada Lovelace',
        email: 'ada@example.com',
        password: GOOD_PASSWORD,
      }),
    )
  })

  it('never keeps the password in state after the request resolves', async () => {
    // On success the form is replaced, so the state is gone with it. The case
    // worth asserting is the one where the form stays on screen: a rejected
    // signup. The password must not survive it, because the reader is going to
    // look at the error and probably retype.
    signUp.mockRejectedValue({ code: 'over_request_rate_limit', message: 'slow down' })
    renderSignup()
    fillValidForm()
    submit()

    await screen.findByText(/wait a minute/i)
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByLabelText('Confirm password')).toHaveValue('')
  })

  // -------------------------------------------------- confirmation required

  it('tells the reader to check their email, and does not claim they are in', async () => {
    signUp.mockResolvedValue(confirmationRequired())
    renderSignup()
    fillValidForm()
    submit()

    expect(await screen.findByRole('heading', { name: /check your email/i })).toBeInTheDocument()
    // The address is named, because that is what they need to go and look at.
    expect(screen.getByText('ada@example.com')).toBeInTheDocument()
    // No success state, and above all no navigation.
    expect(screen.queryByText(/account created/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /fact-checker/i })).not.toBeInTheDocument()
  })

  it('offers a way back to login from the confirmation state', async () => {
    renderSignup()
    fillValidForm()
    submit()

    expect(await screen.findByRole('link', { name: /log in/i })).toHaveAttribute('href', '/login')
  })

  it('replaces the form rather than leaving a dead one under the message', async () => {
    renderSignup()
    fillValidForm()
    submit()

    await screen.findByRole('heading', { name: /check your email/i })
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })

  // ---------------------------------------------------------------- success

  it('redirects to the fact-checker when Supabase returns a session', async () => {
    signUp.mockResolvedValue(signedIn())
    renderSignup()
    fillValidForm()
    submit()

    expect(await screen.findByRole('heading', { name: /fact-checker/i })).toBeInTheDocument()
  })

  it('shows a success beat before leaving, so the outcome is not silent', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      signUp.mockResolvedValue(signedIn())
      renderSignup()
      fillValidForm()
      submit()

      await vi.waitFor(() => expect(signUp).toHaveBeenCalled())
      expect(await screen.findByText(/account created/i)).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  // -------------------------------------------------------------- auth error

  it('shows a real Supabase failure in plain language, and leaks nothing', async () => {
    signUp.mockRejectedValue({
      code: 'user_already_exists',
      message: 'AuthApiError: User already registered',
    })
    renderSignup()
    fillValidForm()
    submit()

    expect(await screen.findByText(/already registered/i)).toBeInTheDocument()
    expect(screen.queryByText(/AuthApiError/i)).not.toBeInTheDocument()
  })

  it('announces the failure as an alert, exactly once', async () => {
    signUp.mockRejectedValue({ code: 'weak_password', message: 'weak' })
    renderSignup()
    fillValidForm()
    submit()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/password/i)
    // The message lives in one live region. A second copy in the polite status
    // would announce the same failure twice.
    expect(screen.getAllByText(/password too weak/i)).toHaveLength(1)
  })

  it('lets the reader try again after a failure', async () => {
    signUp.mockRejectedValue({ code: 'over_request_rate_limit', message: 'slow down' })
    renderSignup()
    fillValidForm()
    submit()

    await screen.findByText(/wait a minute/i)
    expect(screen.getByRole('button', { name: /^create account$/i })).toBeEnabled()
  })

  // ------------------------------------------------------------ not signed in

  it('sends an already-authenticated reader to the fact-checker instead of the form', () => {
    authState.status = 'authenticated'
    authState.user = { id: 'u1', email: 'ada@example.com', user_metadata: { name: 'Ada' } }
    renderSignup()

    expect(screen.getByRole('heading', { name: /fact-checker/i })).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })

  it('says plainly when no project is configured, and refuses to submit', () => {
    authState.configured = false
    renderSignup()

    expect(screen.getByText(/not configured on this deployment/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^create account$/i })).toBeDisabled()
  })

  it('never claims accounts are unavailable when they are available', () => {
    renderSignup()

    expect(screen.queryByText(/accounts are not implemented/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/not available yet/i)).not.toBeInTheDocument()
  })

  // ------------------------------------------------------------- navigation

  it('links to the existing login route', () => {
    renderSignup()

    expect(screen.getByRole('link', { name: /log in/i })).toHaveAttribute('href', '/login')
  })

  it('toggles password visibility for both password fields', () => {
    renderSignup()

    const passwordToggle = screen.getByRole('button', { name: /show password$/i })
    fireEvent.click(passwordToggle)
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'text')

    const confirmToggle = screen.getByRole('button', { name: /show confirm password/i })
    fireEvent.click(confirmToggle)
    expect(screen.getByLabelText('Confirm password')).toHaveAttribute('type', 'text')
  })
})
