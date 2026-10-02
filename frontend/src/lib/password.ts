/**
 * The password rules, in one place.
 *
 * The form, the strength meter and the submit gate all read from here, so the
 * three can never disagree about what a valid password is. Anything that
 * validates a password imports `passwordIssues` rather than writing its own
 * `length >= 8` check.
 *
 * ON THE MINIMUM LENGTH
 *
 * Supabase's own default minimum is 6, which is below anything worth calling a
 * password today. This product requires 8. That is deliberately stricter than the
 * server default: the client gate is the place to be conservative, and Supabase
 * will still reject anything stricter than its own configured minimum, which
 * arrives as a real error we surface. Raising `MIN_PASSWORD_LENGTH` here is
 * therefore always safe, and if the project is configured higher, the user
 * simply gets told by Supabase.
 *
 * ON THE STRENGTH METER
 *
 * It reports the checks that were actually applied, not a score. There is no
 * entropy estimate here, because an entropy number computed in the browser from
 * four character-class tests is a guess dressed as a measurement, and it is
 * exactly the kind of invented certainty this codebase avoids elsewhere. What
 * the reader gets is a list of things their password does and does not yet have,
 * which is both true and actionable.
 */

export const MIN_PASSWORD_LENGTH = 8

export interface PasswordCheck {
  /** A short, factual statement of what is satisfied. */
  label: string
  met: boolean
}

export interface PasswordReview {
  /** Hard problems that block submission. Empty means it is acceptable. */
  issues: string[]
  /** The applied rules, for display. Length check is always present. */
  checks: PasswordCheck[]
  /**
   * 0–3, a coarse band derived only from the checks above. Drives the meter's
   * geometry, never its wording: the wording is the checks.
   */
  level: 0 | 1 | 2 | 3
}

const SYMBOL = /[^A-Za-z0-9]/

/** Everything wrong with a password, in the order a reader would fix it. */
export function passwordIssues(password: string): string[] {
  const issues: string[] = []
  if (password === '') issues.push('Enter a password.')
  else if (password.length < MIN_PASSWORD_LENGTH) {
    issues.push(`Use at least ${MIN_PASSWORD_LENGTH} characters.`)
  }
  return issues
}

/** The rules, each one a thing the reader can act on. */
export function reviewPassword(password: string): PasswordReview {
  const longEnough = password.length >= MIN_PASSWORD_LENGTH
  const lower = /[a-z]/.test(password)
  const upper = /[A-Z]/.test(password)
  const digit = /[0-9]/.test(password)
  const symbol = SYMBOL.test(password)
  const classes = [lower, upper, digit, symbol].filter(Boolean).length

  const checks: PasswordCheck[] = [
    { label: `At least ${MIN_PASSWORD_LENGTH} characters`, met: longEnough },
    { label: 'Upper and lower case', met: lower && upper },
    { label: 'A number', met: digit },
    { label: 'A symbol', met: symbol },
  ]

  // The bands only ever step up on a rule that is visibly checked above, so the
  // meter can never claim more than the list shows.
  let level: 0 | 1 | 2 | 3 = 0
  if (longEnough) level = 1
  if (longEnough && classes >= 2) level = 2
  if (longEnough && password.length >= 12 && classes >= 3) level = 3

  return { issues: passwordIssues(password), checks, level }
}

/** One line describing the next useful thing to change, or nothing to change. */
export function passwordSummary(password: string): string | null {
  if (password === '') return null
  const review = reviewPassword(password)
  if (review.issues.length > 0) return review.issues[0] ?? null
  if (review.level >= 3) return 'Long and varied — a strong password.'
  const missing: string[] = []
  if (!/[A-Z]/.test(password) || !/[a-z]/.test(password)) missing.push('mixed case')
  if (!/[0-9]/.test(password)) missing.push('a number')
  if (!SYMBOL.test(password)) missing.push('a symbol')
  if (password.length < 12) missing.push('a few more characters')
  return missing.length === 0
    ? 'Long and varied — a strong password.'
    : `Stronger with ${missing.join(', ')}.`
}

/**
 * How similar two strings are, 0–1, over the length of the longer one.
 *
 * This is the Damerau ratio rather than plain Levenshtein, and the difference
 * is the whole point. Levenshtein counts an adjacent transposition as *two*
 * edits, so with plain distance a 13-character password with its last two
 * characters swapped scores 0.846 and gets rejected as a mismatch. Damerau
 * counts that as the one edit it is, which scores 0.923 and passes.
 *
 * It matters because this check exists to catch typos, and swapping two
 * characters is the most common typo there is. A ratio computed on the wrong
 * edit model rejects exactly the reader the feature is meant to help.
 */
export function similarity(a: string, b: string): number {
  if (a === b) return 1
  if (a.length === 0 || b.length === 0) return 0

  // A full table rather than rolling rows: the transposition case reaches back
  // two rows, and a password is tens of characters, so the memory is free and
  // the code is legible. The rolling-row version of this is where the bug
  // lives.
  const rows = a.length + 1
  const columns = b.length + 1
  const d: number[][] = Array.from({ length: rows }, () => new Array<number>(columns).fill(0))
  for (let i = 0; i < rows; i += 1) d[i]![0] = i
  for (let j = 0; j < columns; j += 1) d[0]![j] = j

  for (let i = 1; i < rows; i += 1) {
    for (let j = 1; j < columns; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      let best = Math.min(
        d[i - 1]![j]! + 1,
        d[i]![j - 1]! + 1,
        d[i - 1]![j - 1]! + cost,
      )
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        best = Math.min(best, d[i - 2]![j - 2]! + 1)
      }
      d[i]![j] = best
    }
  }

  const distance = d[rows - 1]![columns - 1]!
  return 1 - distance / Math.max(a.length, b.length)
}

/**
 * Whether a confirmation is close enough to the password to be a plausible
 * typo rather than a different password. 0.85 is deliberately strict: near
 * misses at that distance are nearly always a transposition, and letting one
 * through would make the "passwords match" check a lie.
 */
export const CONFIRMATION_TOLERANCE = 0.85

export function confirmMatches(password: string, confirmation: string): boolean {
  if (confirmation === '') return false
  if (password === confirmation) return true
  return password.length > 0 && similarity(password, confirmation) >= CONFIRMATION_TOLERANCE
}
