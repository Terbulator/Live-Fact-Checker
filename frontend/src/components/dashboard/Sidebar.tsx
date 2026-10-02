/**
 * The conversation sidebar.
 *
 * Chat history and nothing else. What is in the product is in here: past checks,
 * a search over them, and a new chat button. There is no navigation between
 * modes, because there are no modes -- the composer is the only input, so a
 * sidebar of input types would be a list of doors to the same room.
 *
 * HISTORY IS REAL
 * The list is whatever this browser has actually run, grouped by when. With
 * nothing stored it says "No conversations yet" rather than showing plausible
 * examples: a fabricated conversation list is the fastest way to make a product
 * look finished when it is not.
 *
 * The active entry is marked with a pale green ground and a green rule rather
 * than a dark fill, so the rail stays as light as the conversation it frames.
 */

import { useMemo, useState } from 'react'
import { LogIn, Plus, Search, Sparkles, X } from 'lucide-react'
import { Link } from 'react-router-dom'

import { GROUP_LABELS, groupOf } from '../../hooks/useConversations'
import type { Conversation, HistoryGroup } from '../../hooks/useConversations'
import { formatRelative } from './thread'

export interface SidebarProps {
  conversations: Conversation[]
  activeId: string
  onSelect: (id: string) => void
  onNewChat: () => void
  /** Drawer state; only meaningful below the drawer breakpoint. */
  open: boolean
  onClose: () => void
  /** Live backend status, so the rail never claims a connection it does not have. */
  status: {
    connected: boolean
    label: string
    detail: string
  }
  account: {
    name: string
    email: string | null
    signedIn: boolean
    /** Sign out. Only rendered when signed in, and only wired when given. */
    onSignOut?: () => void
  }
}

const GROUP_ORDER: HistoryGroup[] = ['today', 'yesterday', 'week', 'older']

export function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNewChat,
  open,
  onClose,
  status,
  account,
}: SidebarProps) {
  const [query, setQuery] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const filtered =
      needle === ''
        ? conversations
        : conversations.filter(
            (entry) =>
              entry.title.toLowerCase().includes(needle) ||
              entry.preview.toLowerCase().includes(needle),
          )

    return GROUP_ORDER.map((group) => ({
      group,
      entries: filtered
        .filter((entry) => groupOf(entry) === group)
        .sort((a, b) => b.updatedAt - a.updatedAt),
    })).filter((section) => section.entries.length > 0)
  }, [conversations, query])

  return (
    <aside className={`side${open ? ' side--open' : ''}`} id="chat-nav" aria-label="Conversations">
      <div className="side__top">
        <Link to="/" className="side__brand" title="Back to the product site">
          <span className="side__mark" aria-hidden="true">
            <Sparkles size={15} />
          </span>
          <span className="side__brandText">
            <h1 className="side__name">Live Fact-Checker</h1>
            <span className="side__tag">Verify claims as they happen.</span>
          </span>
        </Link>

        <button
          type="button"
          className="side__close"
          onClick={onClose}
          aria-label="Close navigation"
        >
          <X size={18} aria-hidden="true" />
        </button>

        <button
          type="button"
          className="side__new"
          onClick={() => {
            onNewChat()
            onClose()
          }}
        >
          <Plus size={16} aria-hidden="true" />
          <span>New chat</span>
        </button>

        <div className="side__search">
          <Search size={14} aria-hidden="true" />
          <input
            type="search"
            value={query}
            placeholder="Search conversations..."
            aria-label="Search conversations"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      <nav className="side__history" aria-label="Conversation history">
        {conversations.length === 0 ? (
          <p className="side__none">No conversations yet</p>
        ) : groups.length === 0 ? (
          <p className="side__none">No conversations match “{query}”</p>
        ) : (
          groups.map((section) => (
            <section key={section.group} className="side__group">
              <h2 className="side__groupLabel">{GROUP_LABELS[section.group]}</h2>
              <ul className="side__list">
                {section.entries.map((entry) => {
                  const isActive = entry.id === activeId
                  return (
                    <li key={entry.id}>
                      <button
                        type="button"
                        className={`side__item${isActive ? ' side__item--active' : ''}`}
                        aria-current={isActive ? 'page' : undefined}
                        onClick={() => {
                          onSelect(entry.id)
                          onClose()
                        }}
                      >
                        <span className="side__itemTitle">{entry.title}</span>
                        <span className="side__itemMeta">
                          <span className="side__itemKind">{describe(entry)}</span>
                          {entry.claims > 0 && (
                            <span>
                              {entry.claims} {entry.claims === 1 ? 'claim' : 'claims'}
                            </span>
                          )}
                          <span>{formatRelative(entry.updatedAt)}</span>
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))
        )}
      </nav>

      <div className="side__foot">
        <p className={`conn${status.connected ? ' conn--on' : ''}`}>
          <span className="conn__dot" aria-hidden="true" />
          <span className="conn__body">
            <strong>{status.label}</strong>
            <span>{status.detail}</span>
          </span>
        </p>

        <div className="account">
          <button
            type="button"
            className="account__button"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            onClick={() => setMenuOpen((value) => !value)}
          >
            <span className="account__avatar" aria-hidden="true">
              {account.name.slice(0, 1).toUpperCase()}
            </span>
            <span className="account__text">
              <strong>{account.name}</strong>
              <span>{account.email ?? 'Not signed in'}</span>
            </span>
            <span className="account__chevron" aria-hidden="true">
              ⌄
            </span>
            {/*
              Only a guest gets the badge. A signed-in reader does not need
              telling that accounts now work, and a "coming soon" chip sitting
              next to a real session would be a lie in the other direction.
            */}
            {!account.signedIn && <span className="side__soon">GUEST</span>}
          </button>

          {menuOpen && (
            <div className="account__menu" role="menu">
              {account.signedIn ? (
                <>
                  <span className="account__menuItem account__menuItem--static" role="menuitem">
                    Signed in
                  </span>
                  <button
                    type="button"
                    className="account__menuItem"
                    role="menuitem"
                    onClick={account.onSignOut}
                    disabled={account.onSignOut === undefined}
                  >
                    <LogIn size={14} aria-hidden="true" />
                    Log out
                  </button>
                </>
              ) : (
                <>
                  <Link to="/login" className="account__menuItem" role="menuitem">
                    <LogIn size={14} aria-hidden="true" />
                    Log in
                  </Link>
                  <Link to="/signup" className="account__menuItem" role="menuitem">
                    <Sparkles size={14} aria-hidden="true" />
                    Create account
                  </Link>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}

function describe(entry: Conversation): string {
  switch (entry.kind) {
    case 'voice':
      return 'Voice'
    case 'video':
      return 'Video'
    case 'audio':
      return 'Audio'
    case 'url':
      return 'Link'
    case 'claim':
    default:
      return 'Claim'
  }
}
