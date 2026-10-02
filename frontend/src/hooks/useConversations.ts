/**
 * Conversation history.
 *
 * The sidebar lists real checks the reader has run in this browser. Entries are
 * created when something is actually submitted, titled from that submission, and
 * stored locally so the list survives a reload.
 *
 * WHAT THIS IS NOT
 * It is not a transcript store. The backend persists sessions and events, but
 * exposes no endpoint for listing or replaying them, so reopening an old
 * conversation here restores its title and its place in the list, not its
 * claims. A title is never fabricated for a check that has not run: with nothing
 * stored the list says so.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { deriveTitle } from '../components/dashboard/thread'
import type { Attachment, RunKind } from '../components/dashboard/thread'

const STORAGE_KEY = 'lfc.conversations.v1'

/** One entry in the history list. */
export interface Conversation {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  /** What the reader sent, for the one-line preview under the title. */
  preview: string
  kind: RunKind
  /** Claim count at the time the entry was last updated. Real, not estimated. */
  claims: number
}

/** Sidebar grouping, derived from a real timestamp. */
export type HistoryGroup = 'today' | 'yesterday' | 'week' | 'older'

export interface UseConversationsResult {
  conversations: Conversation[]
  /** The entry in view, created on demand so there is always a current chat. */
  activeId: string
  active: Conversation | null
  /** Record a real submission, creating or updating the entry for it. */
  beginTurn: (input: { text: string; attachment: Attachment | null; kind: RunKind }) => string
  /** Update the active entry once a run reports how many claims it produced. */
  recordOutcome: (claims: number) => void
  rename: (id: string, title: string) => void
  remove: (id: string) => void
  /** Open an existing conversation. */
  select: (id: string) => void
  /** Start a new conversation. The previous one keeps its place in the list. */
  startNew: () => string
}

function read(): Conversation[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw === null) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(isConversation)
  } catch {
    // A private-mode or corrupted store must not stop the product working; the
    // worst case is a history that starts empty.
    return []
  }
}

function isConversation(value: unknown): value is Conversation {
  if (typeof value !== 'object' || value === null) return false
  const entry = value as Partial<Conversation>
  return (
    typeof entry.id === 'string' &&
    typeof entry.title === 'string' &&
    typeof entry.createdAt === 'number' &&
    typeof entry.updatedAt === 'number'
  )
}

function write(conversations: Conversation[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations))
  } catch {
    // Storage may be unavailable or full. History is a convenience, so the
    // conversation itself continues without it.
  }
}

function mintId(): string {
  return `conv_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`
}

function previewOf(text: string, attachment: Attachment | null): string {
  if (text !== '') return text.length > 90 ? `${text.slice(0, 89)}…` : text
  if (attachment === null) return 'Voice check'
  if (attachment.kind === 'url') return attachment.label
  if (attachment.kind === 'video') return 'Video check'
  return 'Audio check'
}

export function useConversations(): UseConversationsResult {
  const [conversations, setConversations] = useState<Conversation[]>(read)
  const [activeId, setActiveId] = useState<string>(() => mintId())

  // Persist on every change rather than on unload, so a closed tab does not
  // lose the list.
  useEffect(() => {
    write(conversations)
  }, [conversations])

  const beginTurn = useCallback(
    ({ text, attachment, kind }: { text: string; attachment: Attachment | null; kind: RunKind }) => {
      const now = Date.now()
      const id = activeId

      setConversations((current) => {
        const existing = current.find((entry) => entry.id === id)
        if (existing === undefined) {
          return [
            {
              id,
              title: deriveTitle({ text, attachment }),
              preview: previewOf(text, attachment),
              createdAt: now,
              updatedAt: now,
              kind,
              claims: 0,
            },
            ...current,
          ]
        }
        return current.map((entry) =>
          entry.id === id ? { ...entry, updatedAt: now, kind } : entry,
        )
      })

      setActiveId(id)
      return id
    },
    [activeId],
  )

  const recordOutcome = useCallback(
    (claims: number) => {
      setConversations((current) =>
        current.map((entry) =>
          entry.id === activeId && claims > entry.claims
            ? { ...entry, claims, updatedAt: Date.now() }
            : entry,
        ),
      )
    },
    [activeId],
  )

  const rename = useCallback((id: string, title: string) => {
    const trimmed = title.trim()
    if (trimmed === '') return
    setConversations((current) =>
      current.map((entry) =>
        entry.id === id ? { ...entry, title: trimmed, updatedAt: Date.now() } : entry,
      ),
    )
  }, [])

  const remove = useCallback((id: string) => {
    setConversations((current) => current.filter((entry) => entry.id !== id))
  }, [])

  const select = useCallback((id: string) => {
    setActiveId(id)
  }, [])

  const startNew = useCallback(() => {
    const id = mintId()
    setActiveId(id)
    return id
  }, [])

  const active = useMemo(
    () => conversations.find((entry) => entry.id === activeId) ?? null,
    [activeId, conversations],
  )

  return { conversations, activeId, active, beginTurn, recordOutcome, rename, remove, select, startNew }
}

/** Which sidebar section an entry belongs under. */
export function groupOf(conversation: Conversation, now: number = Date.now()): HistoryGroup {
  const startOfToday = new Date(now)
  startOfToday.setHours(0, 0, 0, 0)
  const startOfYesterday = startOfToday.getTime() - 24 * 60 * 60 * 1000

  if (conversation.updatedAt >= startOfToday.getTime()) return 'today'
  if (conversation.updatedAt >= startOfYesterday) return 'yesterday'
  if (conversation.updatedAt >= startOfYesterday - 5 * 24 * 60 * 60 * 1000) return 'week'
  return 'older'
}

export const GROUP_LABELS: Record<HistoryGroup, string> = {
  today: 'Today',
  yesterday: 'Yesterday',
  week: 'Previous 7 days',
  older: 'Earlier',
}
