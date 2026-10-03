import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { useBriefing, useGearList, type Briefing, type GearSummary } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import { shoeWear } from '../../constants/gear'
import { formatDurationHM, formatDist } from '../../utils/formatSpeed'
import { parseLocalDate } from '../../utils/dates'
import { SegmentSummary, type Segment } from '../shared/SegmentListBuilder'
import { hrvTone, readinessTone, restingHrTone, sleepTone, toneColor, type Tone } from '../garmin/garmin'
import { formZone, formatFormPct } from '../analytics/form'
import { sessionGoalChips } from './calendar'
import GoalChips from './GoalChips'
import WatchStatus from './WatchStatus'

const SUGGESTION: Record<NonNullable<Briefing['suggestion']>['tone'], { color: string; label: string }> = {
  caution: { color: '#f59e0b', label: 'Heads-up' },
  go: { color: '#22c55e', label: 'Green light' },
  rest: { color: '#38bdf8', label: 'Recovery' },
  info: { color: '#9ca3af', label: 'Note' },
}

// Shoes this close to their expected life, and still in use, get a heads-up
const GEAR_ALERT_RATIO = 0.9
const GEAR_ACTIVE_DAYS = 30
const DISMISSED_KEY = 'z2-dismissed-gear-alerts'

function readDismissed(): string[] {
  try {
    const raw = localStorage.getItem(DISMISSED_KEY)
    return raw ? JSON.parse(raw) as string[] : []
  } catch {
    return []
  }
}

function gearAlerts(gear: GearSummary[] | undefined, today: string, dismissed: string[]) {
  const since = new Date(`${today}T00:00:00`)
  since.setDate(since.getDate() - GEAR_ACTIVE_DAYS)
  return (gear ?? []).filter(g =>
    g.kind === 'shoes' && !g.retired && !dismissed.includes(g.id)
    && g.last_activity != null && parseLocalDate(g.last_activity) >= since
    && shoeWear(g.distance_km).ratio >= GEAR_ALERT_RATIO,
  )
}

function Tile({ label, value, detail, tone = 'neutral' }: { label: string; value: ReactNode; detail?: string; tone?: Tone }) {
  return (
    <div className="min-w-0">
      <div className="eyebrow text-[9px]">{label}</div>
      <div className="font-mono tabular-nums text-lg font-semibold leading-tight mt-0.5" style={{ color: tone === 'neutral' ? undefined : toneColor(tone) }}>
        {value}
      </div>
      {detail && <div className="text-[11px] text-gray-500 truncate">{detail}</div>}
    </div>
  )
}

const titleCase = (s: string | null | undefined) => (s ? s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, ' ') : '')

/** Today at the top of the calendar: what's planned (or done), how recovered
 *  you are, current form, a suggestion weighing them, and shoe heads-ups. */
export default function MorningBriefing() {
  const { data } = useBriefing()
  const { data: gearList } = useGearList()
  const [dismissed, setDismissed] = useState<string[]>(readDismissed)

  if (!data) return null
  const { recovery: r, form, suggestion } = data
  const alerts = gearAlerts(gearList?.gear, data.date, dismissed)
  const zone = form?.form_pct != null ? formZone(form.form_pct) : null

  const dismiss = (id: string) => {
    const next = [...dismissed, id]
    setDismissed(next)
    try { localStorage.setItem(DISMISSED_KEY, JSON.stringify(next)) } catch { /* private mode: dismissed for this visit only */ }
  }

  return (
    <section className="panel p-4 md:p-5 space-y-4" aria-label="Today">
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <div className="space-y-3 min-w-0">
          <div className="eyebrow !text-blue-400">
            Today · {parseLocalDate(data.date).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}
          </div>
          {data.done.length > 0 ? (
            <div className="space-y-1.5">
              {data.done.map(a => (
                <Link key={a.id} to={`/activities/${a.id}`} className="flex items-center gap-2 group">
                  <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: getSportColor(a.sport_type) }} />
                  <span className="text-sm truncate group-hover:underline">{a.name}</span>
                  <span className="text-[11px] font-mono tabular-nums text-gray-500 shrink-0">
                    {a.distance_km ? formatDist(a.distance_km, a.sport_type) : ''}
                    {a.moving_time ? ` · ${formatDurationHM(a.moving_time)}` : ''}
                  </span>
                  <span className="text-[10px] uppercase tracking-[0.12em] text-green-400 shrink-0">done</span>
                </Link>
              ))}
            </div>
          ) : data.sessions.length > 0 ? (
            <div className="space-y-2.5">
              {data.sessions.map(s => {
                const color = getSportColor(s.sport_type)
                const segments = Array.isArray(s.segments) && s.segments.length > 0 ? s.segments as Segment[] : null
                return (
                  <div key={s.id} className="space-y-1.5">
                    <div className="flex items-baseline gap-2 min-w-0">
                      <span className="text-sm font-semibold shrink-0" style={{ color }}>{s.sport_type}</span>
                      {!!s.description && <span className="text-sm text-gray-400 truncate">{s.description}</span>}
                      <WatchStatus session={s} size={12} className="self-center" />
                    </div>
                    <GoalChips chips={sessionGoalChips(s)} />
                    {segments && <SegmentSummary segments={segments} />}
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-sm text-gray-500">Nothing planned.</div>
          )}
          {suggestion && (
            <div className="border-l-2 pl-3 space-y-0.5" style={{ borderColor: SUGGESTION[suggestion.tone].color }}>
              <div className="eyebrow !text-[9px]" style={{ color: SUGGESTION[suggestion.tone].color }}>
                {SUGGESTION[suggestion.tone].label}
              </div>
              <p className="text-[13px] leading-relaxed text-gray-300">{suggestion.text}</p>
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-3 content-start">
          {r?.readiness && (
            <Tile label="Readiness" value={r.readiness.score}
              detail={`${titleCase(r.readiness.level)}${r.readiness.at_wakeup ? ' · at wake-up' : ''}`}
              tone={readinessTone(r.readiness.score)} />
          )}
          {r?.sleep && (
            <Tile label="Sleep" value={r.sleep.score}
              detail={[titleCase(r.sleep.qualifier), r.sleep.seconds ? formatDurationHM(r.sleep.seconds) : ''].filter(Boolean).join(' · ')}
              tone={sleepTone(r.sleep.qualifier ?? undefined)} />
          )}
          {r?.hrv && (
            <Tile label="HRV" value={<>{r.hrv.last_night}<span className="text-[11px] text-gray-500 ml-1">ms</span></>}
              detail={[titleCase(r.hrv.status), r.hrv.weekly != null ? `7d ${r.hrv.weekly}` : ''].filter(Boolean).join(' · ')}
              tone={hrvTone(r.hrv.status ?? undefined)} />
          )}
          {r?.body_battery && (
            <Tile label="Body battery" value={r.body_battery.at_wake}
              detail={r.body_battery.now != null ? `at wake · now ${r.body_battery.now}` : 'at wake'} />
          )}
          {r?.recovery_hours != null && (
            <Tile label="Recovery" value={<>{r.recovery_hours}<span className="text-[11px] text-gray-500 ml-1">h</span></>}
              detail="until fully recovered" tone={r.recovery_hours >= 24 ? 'neg' : 'neutral'} />
          )}
          {r?.resting_hr && !r.recovery_hours && (
            <Tile label="Resting HR" value={r.resting_hr.today}
              detail={r.resting_hr.avg_7d != null ? `7d ${r.resting_hr.avg_7d}` : undefined}
              tone={restingHrTone(r.resting_hr.today, r.resting_hr.avg_7d)} />
          )}
          {form?.form_pct != null && zone && (
            <Link to="/analytics" className="min-w-0 group">
              <div className="eyebrow text-[9px]">Form</div>
              <div className="font-mono tabular-nums text-lg font-semibold leading-tight mt-0.5" style={{ color: zone.color }}>
                {formatFormPct(form.form_pct)}
              </div>
              <div className="text-[11px] text-gray-500 truncate group-hover:underline">{zone.label}</div>
            </Link>
          )}
        </div>
      </div>

      {alerts.length > 0 && (
        <div className="border-t border-dashed pt-3 space-y-1.5" style={{ borderColor: 'var(--color-surface-600)' }}>
          {alerts.map(g => {
            const wear = shoeWear(g.distance_km)
            return (
              <div key={g.id} className="flex items-center gap-2 text-sm">
                <span className="text-amber-400 shrink-0" aria-hidden="true">●</span>
                <span className="min-w-0 flex-1">
                  <Link to={`/gear/${g.id}`} className={clsx('font-medium hover:underline')}>{g.label}</Link>
                  <span className="text-gray-500"> is at {Math.round(g.distance_km).toLocaleString()} km, {wear.caption}. Time for a new pair?</span>
                </span>
                <button className="action-link text-[11px] text-gray-500 hover:text-gray-300 shrink-0" onClick={() => dismiss(g.id)}>
                  Dismiss
                </button>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
