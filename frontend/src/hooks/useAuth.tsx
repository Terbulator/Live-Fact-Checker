import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import type { Session, SupabaseClient, User } from '@supabase/supabase-js'

import { authRedirectTarget, getSupabase, isSupabaseConfigured } from '../lib/supabase'

/**
 * The application's authentication state.
 *
 * One provider, one Supabase client, one subscription. `/signup`, `/login` and
 * the dashboard sidebar all read from this, which is what keeps them honest: a
 * page cannot claim the reader is signed in when the provider disagrees, because
 * there is only one answer to the question.
 *
 * HOW CONFIRMATION IS HANDLED
 *
 * The brief asks for two different behaviours depending on whether the project
 * has email confirmation switched on. That setting lives in the Supabase
 * dashboard and is not readable from the client, and hardcoding either
 * assumption would be wrong the moment somebody toggled it.
 *
 * So this does not try to know. Supabase answers the question directly in the
 * `signUp` response: if confirmation is disabled it hands back a live `session`,
 * and if it is enabled it hands back a `user` with no session. So the branch is
 * made on that:
 *
 *   session present    -> the account exists and the reader is signed in
 *   session absent     -> the account was created and an email is on its way
 *
 * That is correct under either dashboard setting, and it cannot drift out of
 * sync with the server the way an assumed flag would.
 *
 * WHAT IS NOT STORED HERE
 *
 * No password, ever, at any point. The form holds it in component state for as
 * long as it is being typed and it is gone the moment the request resolves; it
 * is never logged, never put in a URL, and never written to storage. The only
 * thing persisted in the browser is the session token, and that is the SDK's own
 * doing in its own storage layer, which this code never reads directly.
 */

export type AuthStatus =
  /** Still asking Supabase whether there is a session. */
  | 'loading'
  /** A session exists. */
  | 'authenticated'
  /** No session, and Supabase is reachable. */
  | 'anonymous'
  /** No Supabase project configured, so auth cannot run at all. */
  | 'unconfigured'

export type SignUpOutcome =
  /** Confirmation is off: there is a session and the reader is signed in. */
  | { kind: 'signed_in' }
  /** Confirmation is on: the account exists, and an email is on its way. */
  | { kind: 'confirmation_required'; email: string }

export interface SignUpInput {
  name: string
  email: string
  password: string
}

export interface AuthContextValue {
  status: AuthStatus
  user: User | null
  /** The configured project is missing, so the auth pages must not pretend. */
  configured: boolean
  /** Throws with an `AuthError`; callers map it through `friendlyAuthError`. */
  signUp: (input: SignUpInput) => Promise<SignUpOutcome>
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  /** Wait for the first session check to settle. Used by the route guards. */
  ready: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [client, setClient] = useState<SupabaseClient | null>(null)

  // The client is created once, outside of render, and a configuration error is
  // captured as a null client rather than thrown during render.
  useEffect(() => {
    try {
      setClient(getSupabase())
    } catch {
      // A bad key is a deployment mistake. The pages report it as
      // unconfigured rather than the whole app failing to mount.
      setClient(null)
    }
  }, [])

  useEffect(() => {
    if (client === null) {
      setLoading(false)
      return undefined
    }

    let active = true

    // The SDK keeps this subscription alive for the life of the client, and
    // fires immediately with the session it recovered from storage. Reading
    // `getSession()` as well covers the case where the listener has not fired
    // yet, so a page refresh never flashes "signed out" for a signed-in reader.
    void client.auth
      .getSession()
      .then(({ data }) => {
        if (active) setUser(data.session?.user ?? null)
      })
      .catch(() => {
        if (active) setUser(null)
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    const { data: subscription } = client.auth.onAuthStateChange((_event, session) => {
      if (active) setUser(session?.user ?? null)
    })

    return () => {
      active = false
      subscription.subscription.unsubscribe()
    }
  }, [client])

  const signUp = useCallback(
    async ({ name, email, password }: SignUpInput): Promise<SignUpOutcome> => {
      if (client === null) throw new Error('Supabase is not configured')
      const { data, error } = await client.auth.signUp({
        email,
        password,
        options: {
          // There is no profiles table in this project, so the name goes in
          // Supabase Auth's own user metadata, which is what `user.user_metadata`
          // and the JWT carry. Adding a table for one string would be a new
          // piece of infrastructure to keep in sync for no gain.
          data: { name },
          // Where a confirmed account lands. Same origin, so it is correct in
          // local dev and in every preview deployment.
          emailRedirectTo: authRedirectTarget(),
        },
      })
      // `error` is a value, not an exception, and the SDK does not throw for a
      // rejected signup. It has to be checked before the data is read.
      if (error !== null) throw error
      if (data.user === null) throw new Error('Supabase returned no user for this signup')
      if (data.session !== null) return { kind: 'signed_in' }
      return { kind: 'confirmation_required', email: data.user.email ?? email }
    },
    [client],
  )

  const signIn = useCallback(
    async (email: string, password: string) => {
      if (client === null) throw new Error('Supabase is not configured')
      const { data, error } = await client.auth.signInWithPassword({ email, password })
      if (error !== null) throw error
      setUser(data.user)
    },
    [client],
  )

  const signOut = useCallback(async () => {
    if (client === null) return
    const { error } = await client.auth.signOut()
    if (error !== null) throw error
    setUser(null)
  }, [client])

  const value = useMemo<AuthContextValue>(() => {
    const status: AuthStatus = !isSupabaseConfigured
      ? 'unconfigured'
      : loading
        ? 'loading'
        : user === null
          ? 'anonymous'
          : 'authenticated'
    return {
      status,
      user,
      configured: isSupabaseConfigured,
      signUp,
      signIn,
      signOut,
      ready: !loading,
    }
  }, [loading, user, signUp, signIn, signOut])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (value === null) {
    throw new Error('useAuth must be used inside an <AuthProvider>')
  }
  return value
}

/**
 * The reader's name, from wherever it is actually available.
 *
 * Supabase stores the name we passed at signup in `user_metadata`, and also
 * offers a `full_name` on the user object itself. Both are read so this works
 * regardless of which one a given project populates.
 */
export function displayName(user: User | null): string {
  if (user === null) return 'Guest'
  const metadata = user.user_metadata as { name?: unknown; full_name?: unknown } | undefined
  for (const candidate of [metadata?.name, metadata?.full_name, user.user_metadata?.name]) {
    if (typeof candidate === 'string' && candidate.trim() !== '') return candidate.trim()
  }
  if (typeof user.email === 'string' && user.email !== '') {
    return user.email.split('@')[0] ?? user.email
  }
  return 'Guest'
}

/** Re-exported so pages need only one auth import. */
export type { Session }
