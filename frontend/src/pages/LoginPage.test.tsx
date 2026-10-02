/**
 * Login screen behaviour.
 *
 * These assert the two things that matter now that login is real: the form is
 * wired to the shared auth provider rather than to nothing, and the page says
 * nothing untrue about it. The previous version of this file asserted the
 * opposite — that the submit was inert and the page admitted accounts did not
 * exist — because that was true when it was written. Those assertions are gone
 * rather than inverted, so nothing here can quietly pass against a dead form.
 *
 * The Supabase call is mocked at the client boundary. No test in this repository
 * can reach a real project or a real account.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { LoginPage } from './LoginPage'

const signIn = vi.fn()
const signOut = vi.fn()
const authState = {
  status: 'anonymous' as string,
  user: null,
  configured: true,
  signIn,
  signOut,
}

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    ...authState,
    ready: true,
    signUp: vi.fn(),
  }),
  displayName: () => 'Guest',
}))

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/dashboard" element={<h1>Fact-checker</h1>} />
      </Routes>
    </MemoryRouter>,
  )
}

function fillIn(password = 'correct-horse') {
  fireEvent.change(screen.getByLabelText('Email address'), {
    target: { value: 'ada@example.com' },
  })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
}

beforeEach(() => {
  signIn.mockReset()
  signOut.mockReset()
  authState.status = 'anonymous'
  authState.user = null
  authState.configured = true
  signIn.mockResolvedValue(undefined)
})

describe('LoginPage', () => {
  it('leads with the brand, then the pitch, then the form', () => {
    renderLogin()

    expect(screen.getByRole('link', { name: /live fact checker home/i })).toHaveAttribute('href', '/')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/truth\s*moves\s*with you/i)
    expect(screen.getByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
  })

  it('keeps the headline accent on the word the copy is about', () => {
    const { container } = renderLogin()

    const accent = container.querySelector('.lfp-auth__headlineAccent')
    expect(accent).toHaveTextContent('moves')
  })

  it('labels both fields and never relies on the placeholder alone', () => {
    renderLogin()

    expect(screen.getByLabelText('Email address')).toHaveAttribute('type', 'email')
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password')
    // The browser's own autofill needs these, and they also tell a password
    // manager this is a sign-in rather than a new credential.
    expect(screen.getByLabelText('Email address')).toHaveAttribute('autocomplete', 'email')
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'current-password')
  })

  it('gives the visibility toggle an accessible name', () => {
    renderLogin()

    const toggle = screen.getByRole('button', { name: /show password/i })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: /hide password/i })).toHaveAttribute('aria-pressed', 'true')
  })

  it('signs in for real and lands on the fact-checker', async () => {
    renderLogin()
    fillIn()

    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }))

    await waitFor(() => expect(signIn).toHaveBeenCalledWith('ada@example.com', 'correct-horse'))
    expect(await screen.findByRole('heading', { name: /fact-checker/i })).toBeInTheDocument()
  })

  it('shows the Supabase failure in plain language, and never a raw message', async () => {
    signIn.mockRejectedValue({
      code: 'invalid_credentials',
      message: 'AuthApiError: invalid login credentials',
    })
    renderLogin()
    fillIn('wrong-password')

    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }))

    expect(await screen.findByText(/do not match an account/i)).toBeInTheDocument()
    expect(screen.queryByText(/AuthApiError/i)).not.toBeInTheDocument()
    // And it must not have navigated anywhere.
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeInTheDocument()
  })

  it('cannot be submitted twice while a request is in flight', async () => {
    let release: (() => void) | undefined
    signIn.mockImplementation(() => new Promise<void>((resolve) => { release = resolve }))
    renderLogin()
    fillIn()

    const button = screen.getByRole('button', { name: /^sign in$/i })
    fireEvent.click(button)
    await waitFor(() => expect(button).toBeDisabled())
    fireEvent.click(button)

    expect(signIn).toHaveBeenCalledTimes(1)
    release?.()
  })

  it('says plainly when no account system is configured, instead of pretending', () => {
    authState.configured = false
    renderLogin()

    expect(screen.getByText(/not configured on this deployment/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeDisabled()
  })

  it('does not claim accounts are unavailable when they are available', () => {
    renderLogin()

    // The old page carried this notice. Nothing may reintroduce it.
    expect(screen.queryByText(/accounts are not implemented/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/no authentication service/i)).not.toBeInTheDocument()
  })

  it('sends a reader who is already signed in to the fact-checker', () => {
    authState.status = 'authenticated'
    authState.user = { id: 'u1', email: 'ada@example.com', user_metadata: { name: 'Ada' } }
    renderLogin()

    expect(screen.getByRole('heading', { name: /fact-checker/i })).toBeInTheDocument()
  })

  it('routes between login and signup', () => {
    renderLogin()

    expect(screen.getByRole('link', { name: /create account/i })).toHaveAttribute('href', '/signup')
  })

  it('lists the capabilities as headings, not as decoration', () => {
    renderLogin()

    expect(screen.getByRole('heading', { name: /video analysis/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /url verification/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /source-backed evidence/i })).toBeInTheDocument()
  })

  it('marks the energy field decorative so it is never announced', () => {
    const { container } = renderLogin()

    const field = container.querySelector('.lfp-auth__energy')
    expect(field).toHaveAttribute('aria-hidden', 'true')
  })
})
