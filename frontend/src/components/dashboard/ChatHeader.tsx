/**
 * The conversation header.
 *
 * The name of the thing being discussed, how long ago it started, and three
 * things a reader may want to do with it. Deliberately minimal: no navigation,
 * no metrics, no status -- the conversation is the page.
 *
 * Renaming is inline and immediate. Sharing copies the conversation's own link,
 * which is honest about what this product has: a URL, not a published report.
 */

import { useEffect, useRef, useState } from 'react'
import { Check, Link2, Menu, MoreHorizontal, Pencil, X } from 'lucide-react'

import { formatRelative } from './thread'

export interface ChatHeaderProps {
  title: string
  createdAt: number | null
  now: number
  onRename: (title: string) => void
  onNewChat: () => void
  /** Opens the conversation drawer on a narrow screen. */
  onMenu: () => void
  /** True while a run is working, so the header can say the chat is provisional. */
  busy: boolean
}

export function ChatHeader({ title, createdAt, now, onRename, onNewChat, onMenu, busy }: ChatHeaderProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(title)
  const [copied, setCopied] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => setDraft(title), [title])

  useEffect(() => {
    if (editing) inputRef.current?.select()
  }, [editing])

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 2200)
    return () => window.clearTimeout(timer)
  }, [copied])

  const commit = () => {
    setEditing(false)
    if (draft.trim() !== '' && draft.trim() !== title) onRename(draft)
    else setDraft(title)
  }

  const share = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
    } catch {
      // A browser that refuses clipboard access gets no confirmation rather than
      // a lie saying the link was copied.
      setCopied(false)
    }
  }

  return (
    <header className="head">
      <span className="head__mark" aria-hidden="true" />

      <div className="head__title">
        {editing ? (
          <>
            <input
              ref={inputRef}
              className="head__input"
              value={draft}
              aria-label="Conversation name"
              onChange={(event) => setDraft(event.target.value)}
              onBlur={commit}
              onKeyDown={(event) => {
                if (event.key === 'Enter') commit()
                if (event.key === 'Escape') {
                  setDraft(title)
                  setEditing(false)
                }
              }}
            />
            <button type="button" className="head__iconBtn" onClick={commit} aria-label="Save name">
              <Check size={15} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="head__iconBtn"
              onClick={() => {
                setDraft(title)
                setEditing(false)
              }}
              aria-label="Cancel rename"
            >
              <X size={15} aria-hidden="true" />
            </button>
          </>
        ) : (
          <>
            <h2 className="head__name">{title}</h2>
            <button
              type="button"
              className="head__iconBtn"
              onClick={() => setEditing(true)}
              aria-label="Rename conversation"
              title="Rename"
            >
              <Pencil size={13} aria-hidden="true" />
            </button>
          </>
        )}
        <p className="head__sub">
          {createdAt === null
            ? busy
              ? 'Working…'
              : 'Nothing submitted yet'
            : `Started ${formatRelative(createdAt, now)}`}
        </p>
      </div>

      <div className="head__actions">
        <button type="button" className="head__menuBtn" onClick={onMenu} aria-label="Open conversations">
          <Menu size={16} aria-hidden="true" />
        </button>

        <button type="button" className="head__btn" onClick={() => void share()}>
          {copied ? <Check size={15} aria-hidden="true" /> : <Link2 size={15} aria-hidden="true" />}
          {copied ? 'Copied' : 'Share'}
        </button>

        <div className="head__menu">
          <button
            type="button"
            className="head__iconBtn"
            aria-label="More actions"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            onClick={() => setMenuOpen((value) => !value)}
          >
            <MoreHorizontal size={16} aria-hidden="true" />
          </button>
          {menuOpen && (
            <div className="head__menuList" role="menu">
              <button
                type="button"
                role="menuitem"
                className="head__menuItem"
                onClick={() => {
                  setMenuOpen(false)
                  setEditing(true)
                }}
              >
                Rename
              </button>
              <button
                type="button"
                role="menuitem"
                className="head__menuItem"
                onClick={() => {
                  setMenuOpen(false)
                  onNewChat()
                }}
              >
                New chat
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
