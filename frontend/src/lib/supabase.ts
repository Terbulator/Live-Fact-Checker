/**
 * The one Supabase client.
 *
 * There is exactly one of these in the bundle, created lazily on first use and
 * then shared. That matters for more than tidiness: `createClient` installs a
 * listener on the browser's storage and its own cross-tab broadcast, and two
 * clients on one page will fight over the same session — one will hold a stale
 * token and overwrite the other's refresh. Every caller goes through
 * `getSupabase()`; nothing calls `createClient` directly.
 *
 * WHAT IS AND IS NOT A SECRET HERE
 *
 * The URL and the publishable/anon key are both designed to reach the browser.
 * Vite inlines every `VITE_*` variable into the JavaScript bundle, so anything
 * here is public the moment the site is deployed. That is fine for the anon key:
 * Supabase's row level security is the thing that actually protects rows, and
 * the anon role only gets what the policies grant.
 *
 * It is emphatically NOT fine for the service-role key, which bypasses RLS
 * entirely. Shipping one to a frontend hands every visitor the whole database.
 * `assertPublishableKey` below refuses to boot if that is what it finds in
 * `VITE_SUPABASE_ANON_KEY`, so a careless copy-paste fails loudly and
 * immediately instead of leaking quietly at deploy time.
 *
 * CONFIGURATION
 *
 * Two variables, both read from the Vite env:
 *
 *   VITE_SUPABASE_URL        https://<project-ref>.supabase.co
 *   VITE_SUPABASE_ANON_KEY   the publishable or anon key
 *
 * See `.env.example`. When they are absent the app still runs: `getSupabase()`
 * returns `null`, `isSupabaseConfigured` is false, and the auth pages say so and
 * refuse to submit. The fact-checker itself has nothing to do with auth and
 * keeps working.
 */

import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const URL = import.meta.env.VITE_SUPABASE_URL?.trim() ?? ''
const ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY?.trim() ?? ''

/**
 * Whether a real project is configured. The auth pages use this to be honest
 * rather than to fail at the moment of submit.
 */
export const isSupabaseConfigured: boolean = URL !== '' && ANON_KEY !== ''

export class SupabaseKeyError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'SupabaseKeyError'
  }
}

/**
 * Read the `role` claim out of a legacy-format Supabase JWT.
 *
 * Returns null for anything that is not a decodable JWT, which includes the
 * modern opaque `sb_publishable_` key — that format is handled by prefix.
 */
function readJwtRole(jwt: string): string | null {
  const parts = jwt.split('.')
  if (parts.length !== 3 || parts[1] === undefined) return null
  try {
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'))) as {
      role?: unknown
    }
    return typeof payload.role === 'string' ? payload.role : null
  } catch {
    return null
  }
}

/**
 * Fail loudly if the configured key is a server-side credential.
 *
 * A service-role key in a browser bundle is a full database compromise, and it
 * is the single most likely way this feature could be shipped wrong — the key
 * is right there in the dashboard under the same heading as the anon key. So
 * the two known shapes of it are rejected at start-up rather than used.
 */
function assertPublishableKey(key: string): void {
  if (key.startsWith('sb_secret_')) {
    throw new SupabaseKeyError(
      'VITE_SUPABASE_ANON_KEY is a sb_secret_ key. Secret keys bypass row level ' +
        'security and must never be used in a browser bundle. Use the publishable ' +
        'or anon key instead.',
    )
  }
  const role = readJwtRole(key)
  if (role === 'service_role') {
    throw new SupabaseKeyError(
      'VITE_SUPABASE_ANON_KEY is a service-role key. It bypasses row level ' +
        'security and must never be used in a browser bundle. Use the publishable ' +
        'or anon key instead.',
    )
  }
}

let client: SupabaseClient | null = null
let failure: string | null = null

/**
 * The shared client, or null when no project is configured.
 *
 * Throws `SupabaseKeyError` if the configured key is a server-side credential —
 * that is a build-time mistake and must not degrade into a confusing runtime
 * error somewhere inside the SDK.
 */
export function getSupabase(): SupabaseClient | null {
  if (!isSupabaseConfigured) return null
  if (client !== null) return client
  if (failure !== null) throw new SupabaseKeyError(failure)

  try {
    assertPublishableKey(ANON_KEY)
  } catch (error) {
    failure = error instanceof Error ? error.message : String(error)
    throw new SupabaseKeyError(failure)
  }

  client = createClient(URL, ANON_KEY, {
    auth: {
      // The SDK's default, stated explicitly because this app relies on it: the
      // session has to survive a reload for the dashboard to remember who is
      // signed in. The token lives in the browser's own storage, managed by the
      // SDK — this app never reads or writes it.
      persistSession: true,
      autoRefreshToken: true,
      // Handles the fragment on an email-confirmation callback link, exchanging
      // it for a session on arrival.
      detectSessionInUrl: true,
    },
  })
  return client
}

/**
 * Where a confirmed signup should land. Same origin, so it works in preview
 * deployments and locally without a hardcoded host.
 */
export function authRedirectTarget(): string {
  return `${window.location.origin}/dashboard`
}
