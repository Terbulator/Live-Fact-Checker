/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the backend HTTP API, e.g. http://127.0.0.1:8000 */
  readonly VITE_BACKEND_URL?: string
  /**
   * Supabase project URL, e.g. https://abcdefghijklm.supabase.co
   *
   * Public. It identifies the project and is safe to ship to the browser.
   */
  readonly VITE_SUPABASE_URL?: string
  /**
   * Supabase publishable / anon key. Public by design: Supabase's row level
   * security is what protects data, and the key only ever grants the anonymous
   * role.
   *
   * This must NEVER be a service-role or `sb_secret_` key. Those bypass RLS and
   * would hand every visitor full access to the database. `lib/supabase.ts`
   * refuses to start if it is given one.
   */
  readonly VITE_SUPABASE_ANON_KEY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
