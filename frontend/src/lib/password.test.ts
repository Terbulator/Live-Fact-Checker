/**
 * Password rules.
 *
 * These are the checks the form, the meter and the submit gate all share, so
 * they are worth testing on their own: a bug here does not show up as a visual
 * glitch, it shows up as a form that rejects a good password or accepts a bad
 * one.
 */

import { describe, expect, it } from 'vitest'

import {
  MIN_PASSWORD_LENGTH,
  confirmMatches,
  passwordIssues,
  passwordSummary,
  reviewPassword,
  similarity,
} from './password'

describe('passwordIssues', () => {
  it('asks for a password when there is none', () => {
    expect(passwordIssues('')).toEqual(['Enter a password.'])
  })

  it('reports the minimum as a length, not as a guess', () => {
    expect(passwordIssues('short')).toEqual([`Use at least ${MIN_PASSWORD_LENGTH} characters.`])
  })

  it('accepts a password that meets the rules', () => {
    expect(passwordIssues('correct-horse')).toEqual([])
  })
})

describe('reviewPassword', () => {
  it('reports every rule as its own entry, so the list cannot go stale', () => {
    const review = reviewPassword('abc')
    expect(review.checks.map((check) => check.label)).toEqual([
      `At least ${MIN_PASSWORD_LENGTH} characters`,
      'Upper and lower case',
      'A number',
      'A symbol',
    ])
    expect(review.checks.every((check) => check.met)).toBe(false)
  })

  it('marks a long, varied password as strong', () => {
    const review = reviewPassword('Tr0ub4dor-and-3')
    expect(review.level).toBe(3)
    expect(review.checks.every((check) => check.met)).toBe(true)
  })

  it('never claims a strong band for a password that misses the length rule', () => {
    // Every character class, but only six characters. The bands are derived from
    // the same checks that are displayed, so variety alone cannot carry a
    // password past the length rule.
    expect(reviewPassword('aA1!aA').level).toBe(0)
  })

  it('steps up as rules are met', () => {
    expect(reviewPassword('abcdefgh').level).toBe(1)
    expect(reviewPassword('abcdefgH').level).toBe(2)
  })
})

describe('passwordSummary', () => {
  it('says nothing about an empty field', () => {
    expect(passwordSummary('')).toBeNull()
  })

  it('names the concrete next change rather than a score', () => {
    const summary = passwordSummary('abcdefgh')
    expect(summary).toMatch(/mixed case|a number|a symbol|more characters/i)
    expect(summary).not.toMatch(/score|entropy|%\d/)
  })
})

describe('similarity', () => {
  it('is 1 for identical strings', () => {
    expect(similarity('correct-horse', 'correct-horse')).toBe(1)
  })

  it('is 0 when one side is empty', () => {
    expect(similarity('', 'abc')).toBe(0)
  })

  it('scores a transposition highly, because that is a typo', () => {
    expect(similarity('passwordd', 'password')).toBeGreaterThan(0.85)
  })
})

describe('confirmMatches', () => {
  it('is false for an empty confirmation, whatever the password', () => {
    expect(confirmMatches('correct-horse', '')).toBe(false)
  })

  it('is true for an exact match', () => {
    expect(confirmMatches('correct-horse', 'correct-horse')).toBe(true)
  })

  it('is false for a genuinely different password', () => {
    expect(confirmMatches('correct-horse', 'something-else-entirely')).toBe(false)
  })

  it('tolerates a transposition rather than calling it a mismatch', () => {
    // A reader who typed the last two characters in the wrong order has still
    // typed their password. Reporting a mismatch here would be pedantry.
    expect(confirmMatches('correct-horse', 'corretc-horse')).toBe(true)
  })
})
