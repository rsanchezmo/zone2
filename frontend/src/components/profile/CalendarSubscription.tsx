import { useState } from 'react'
import clsx from 'clsx'
import { useRotateCalendarFeedToken, type CalendarFeedUrl } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { useToast } from '../../hooks/useToast'
import { useNow } from '../../hooks/useNow'

/** The iCal feed of planned sessions, for Google/Apple Calendar → phone → Garmin watch. */
export default function CalendarSubscription({ feedUrl }: { feedUrl: CalendarFeedUrl | undefined }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()
  const [showSubscribe, setShowSubscribe] = useState(false)
  const rotateFeedToken = useRotateCalendarFeedToken()

  function handleCopyFeedUrl() {
    if (!feedUrl?.url) return
    navigator.clipboard.writeText(feedUrl.url).then(
      () => toast('Feed URL copied', 'success'),
      () => toast('Could not copy — select the text manually', 'error'),
    )
  }

  function handleRotateFeedToken() {
    if (!window.confirm('Rotate the feed token? Any existing calendar subscription will stop working — you will need to re-add the new URL.')) return
    rotateFeedToken.mutate(undefined, {
      onSuccess: () => toast('Token rotated — re-subscribe with the new URL', 'success'),
    })
  }

  return (
    <section>
      <div className="eyebrow mb-3">Calendar subscription</div>
      <div className={clsx('rounded-lg border', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
        <button
          onClick={() => setShowSubscribe(v => !v)}
          className={clsx('w-full flex items-center justify-between px-4 py-2.5 text-left', isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700/50')}
        >
          <span className="flex items-center gap-2">
            <span className="text-sm">Subscribe in Google Calendar</span>
            <FeedStatusPill lastFetchedAt={feedUrl?.last_fetched_at ?? null} />
          </span>
          <span className="text-xs text-gray-500 tabular-nums">{showSubscribe ? '−' : '+'}</span>
        </button>
        {showSubscribe && (
          <div className={clsx('px-4 pb-3 pt-1 space-y-2 border-t', isLight ? 'border-gray-200' : 'border-surface-600')}>
            <div className="flex gap-2 items-center">
              <input
                readOnly
                value={feedUrl?.url ?? 'Loading…'}
                onFocus={e => e.currentTarget.select()}
                className={clsx('flex-1 font-mono text-[11px] px-2 py-1.5 rounded border min-w-0', isLight ? 'bg-gray-50 border-gray-200 text-gray-700' : 'bg-surface-900 border-surface-600 text-gray-300')}
              />
              <button onClick={handleCopyFeedUrl} className="btn text-xs" disabled={!feedUrl?.url}>Copy</button>
              <button
                onClick={handleRotateFeedToken}
                className="btn text-xs"
                disabled={rotateFeedToken.isPending || feedUrl?.env_managed}
                title={feedUrl?.env_managed ? 'Token is pinned via STRAVA_WEB_CALENDAR_FEED_TOKEN — rotate it in .env and restart' : undefined}
              >
                {rotateFeedToken.isPending ? 'Rotating…' : 'Rotate'}
              </button>
            </div>
            <p className="text-[11px] text-gray-500 leading-relaxed">
              Paste into Google Calendar → <b>Other calendars</b> → <b>From URL</b>. Events refresh every few hours.
              Your phone (and paired Garmin watch) pick it up automatically — Android/iOS users may need to toggle
              Sync on in Google Calendar settings the first time. Keep the URL private: anyone with it can read your plan.
              {feedUrl?.env_managed && (
                <> Token is pinned via <code>STRAVA_WEB_CALENDAR_FEED_TOKEN</code> in <code>.env</code>.</>
              )}
            </p>
          </div>
        )}
      </div>
    </section>
  )
}

// ────────────────────────────────────────────────────────
// FeedStatusPill — shows whether the ICS feed has been polled recently
// ────────────────────────────────────────────────────────
function FeedStatusPill({ lastFetchedAt }: { lastFetchedAt: string | null }) {
  const now = useNow(60_000)
  if (!lastFetchedAt) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded border bg-amber-500/10 border-amber-500/30 text-amber-600">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500" /> Not subscribed yet
      </span>
    )
  }

  const last = new Date(lastFetchedAt)
  const ageMs = now - last.getTime()
  const ageHours = ageMs / (1000 * 60 * 60)
  // Google typically polls subscribed ICS every few hours. 25h gives headroom
  // for the occasional slower refresh before we flag it as stale.
  const isActive = ageHours < 25

  const relative = formatRelative(ageMs)
  const tone = isActive
    ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600'
    : 'bg-amber-500/10 border-amber-500/30 text-amber-600'
  const dotTone = isActive ? 'bg-emerald-500' : 'bg-amber-500'
  const label = isActive ? `Active · polled ${relative}` : `Stale · ${relative}`

  return (
    <span className={clsx('inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded border', tone)} title={`Last fetch: ${last.toLocaleString()}`}>
      <span className={clsx('w-1.5 h-1.5 rounded-full', dotTone)} /> {label}
    </span>
  )
}

function formatRelative(ms: number): string {
  const sec = Math.max(0, Math.floor(ms / 1000))
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 48) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  return `${day}d ago`
}
