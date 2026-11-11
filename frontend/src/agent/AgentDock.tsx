import { lazy, Suspense, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import { useAgentStatus } from '../api/hooks'
import { useTheme } from '../hooks/useTheme'
import { COACH } from '../components/coach/colors'
import { useEscapeKey } from '../hooks/useEscapeKey'
import { RobotIcon } from '../components/icons'
import { pageContext } from './pageContext'

// The conversation and its Markdown renderer load on first use, not with every page
const loadChat = () => import('./AgentChat')
const AgentChat = lazy(loadChat)

const EXPANDED_KEY = 'z2-agent-expanded'
// z-[1100]: above Leaflet's panes and controls (up to 1000) on the map pages, below dialogs (~10000)

function stored(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}

function store(key: string, value: string | null) {
  try {
    if (value) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  } catch { /* private mode: lasts this page load */ }
}

/** The agent on every page: a button bottom-right, and the conversation above it. */
export default function AgentDock() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const location = useLocation()
  const navigate = useNavigate()
  const page = pageContext(location.pathname, location.search)
  const { data: status } = useAgentStatus()
  const [open, setOpen] = useState(false)
  // The chat stays mounted once opened, so its transcript and draft outlive closing the panel
  const [started, setStarted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(() => stored(EXPANDED_KEY) === '1')
  const unread = status?.unread ?? 0
  const offline = status != null && !status.available
  useEscapeKey(open, close)

  function show() {
    setStarted(true)
    setOpen(true)
  }

  function close() {
    setOpen(false)
  }

  function toggleExpanded() {
    setExpanded(e => {
      store(EXPANDED_KEY, e ? null : '1')
      return !e
    })
  }

  function openPage(path: string) {
    // The page opens behind the chat, so an expanded chat steps aside for this once
    setExpanded(false)
    navigate(path)
  }

  const surface = clsx('bg-surface-800/95 border-surface-600', isLight ? 'text-gray-900' : 'text-gray-100')
  const coach = isLight ? COACH.light : COACH.dark

  return (
    <>
      {started && (
        <div
          role="dialog"
          aria-label="Coach"
          className={clsx(
            open ? 'flex' : 'hidden',
            'fixed z-[1100] rounded-2xl border backdrop-blur flex-col overflow-hidden shadow-2xl',
            expanded
              ? 'inset-x-2 top-16 bottom-20 sm:inset-x-auto sm:right-6 sm:top-6 sm:bottom-24 sm:w-[min(760px,calc(100vw-8rem))]'
              : 'right-4 bottom-24 sm:right-6 w-[calc(100vw-2rem)] sm:w-[380px] h-[min(70vh,620px)]',
            surface,
          )}
          style={{ ['--coach' as string]: coach, borderTopColor: coach, borderTopWidth: 2 }}
        >
          <div className={'flex items-center gap-3 px-4 py-3 border-b border-surface-600'}>
            <span className="w-8 h-8 rounded-full flex items-center justify-center shrink-0" style={{ backgroundColor: `${coach}22`, color: coach }} aria-hidden="true">
              <RobotIcon size={17} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="eyebrow" style={{ color: coach }}>Coach</div>
              <div className="text-[11px] text-gray-500 truncate">on {page}</div>
            </div>
            <button
              className="text-gray-500 hover:text-gray-300"
              onClick={toggleExpanded}
              aria-label={expanded ? 'Make the coach smaller' : 'Make the coach bigger'}
              title={expanded ? 'Smaller' : 'Bigger'}
            >
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                {expanded
                  ? <path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" />
                  : <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />}
              </svg>
            </button>
            <button className="text-gray-500 hover:text-gray-300 text-lg leading-none" aria-label="Close" onClick={close}>×</button>
          </div>

          <Suspense fallback={
            <div className="flex-1 flex items-center justify-center text-gray-500">
              <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
            </div>
          }>
            <AgentChat open={open} expanded={expanded} busy={busy} onBusyChange={setBusy} onOpenPage={openPage} />
          </Suspense>
        </div>
      )}

      <button
        type="button"
        onClick={() => (open ? close() : show())}
        // Fetched on intent, so the chat is usually there by the time the click lands
        onPointerEnter={() => void loadChat()}
        onFocus={() => void loadChat()}
        aria-label={offline ? 'Coach, not connected' : open ? 'Close the coach' : unread > 0 ? `Talk to the coach, ${unread} new` : 'Talk to the coach'}
        title={offline ? `Not connected: no key for ${status?.model}` : 'Coach'}
        aria-expanded={open}
        className={clsx(
          'fixed z-[1100] right-4 bottom-4 sm:right-6 sm:bottom-6 w-14 h-14 rounded-full border backdrop-blur flex items-center justify-center transition-colors',
          offline
            ? 'bg-red-500/15 border-red-500/50 text-red-500'
            : isLight ? 'bg-teal-50/95 border-teal-300 text-teal-700 hover:border-teal-500' : 'bg-teal-400/10 border-teal-400/40 text-teal-300 hover:border-teal-300/70',
          busy && !open && 'animate-pulse',
        )}
      >
        <RobotIcon size={24} aria-hidden="true" />
        {unread > 0 && !open && (
          <span className="absolute -top-0.5 -right-0.5 min-w-5 h-5 px-1 rounded-full bg-red-500 text-white text-[11px] font-semibold leading-5 text-center tabular-nums">
            {unread}
          </span>
        )}
      </button>
    </>
  )
}
