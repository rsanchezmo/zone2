import { useState, useMemo } from 'react'
import { format, addDays, parseISO } from 'date-fns'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import type { Activity, GoalProgress, TrainingSession, WeeklyReport } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import { WEEKDAY_LETTERS } from '../../constants/weekdays'
import { useTheme } from '../../hooks/useTheme'
import { formatDurationHM } from '../../utils/formatSpeed'
import { parseLocalDate } from '../../utils/dates'
import { formatGoalProgress, GOAL_DONE_COLOR } from '../../utils/goals'
import ExportButton from '../shared/ExportButton'
import GoalProgressBar from '../shared/GoalProgressBar'
import { SegmentSummary, type Segment } from '../shared/SegmentListBuilder'
import { formatWeekRange, sessionGoalChips } from './calendar'
import GoalChips from './GoalChips'

/* ── Planned sessions for the inspected week (expandable) ── */
interface PlannedSessionsProps {
  sessions: TrainingSession[] | undefined
  todayStr: string
  /** Monday of the week these sessions belong to. */
  weekStart: string
  /** Opens the day the athlete picked to plan on. */
  onPickDay: (date: string) => void
}

function PlannedSessions({ sessions, todayStr, weekStart, onPickDay }: PlannedSessionsProps) {
  const [expandedId, setExpandedId] = useState<number | null>(null)

  return (
    <div>
      <div className="eyebrow !text-[9px] mb-2">Planned this week</div>
      {sessions && sessions.length > 0 ? (
        <div className="space-y-2">
          {sessions.map(s => {
            const color = getSportColor(s.sport_type)
            const sessionDate = parseLocalDate(s.date)
            const isTodaySession = s.date === todayStr
            const isExpanded = expandedId === s.id
            return (
              <div
                key={s.id as number}
                className="rounded-lg border border-dashed transition-colors cursor-pointer"
                style={{ borderColor: `${color}40` }}
                onClick={() => setExpandedId(isExpanded ? null : s.id as number)}
              >
                <div className="flex items-center gap-3 px-3 py-2">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
                  <span className="text-sm font-medium shrink-0" style={{ color }}>{String(s.sport_type)}</span>
                  {!isExpanded && !!s.description && (
                    <span className="text-sm text-gray-400 truncate flex-1">{String(s.description)}</span>
                  )}
                  {(!s.description || isExpanded) && <span className="flex-1" />}
                  <span className="text-xs text-gray-500 shrink-0">
                    {isTodaySession ? 'Today' : format(sessionDate, 'EEE, MMM d')}
                  </span>
                  <span className="text-[10px] text-gray-600 shrink-0">{isExpanded ? '▲' : '▼'}</span>
                </div>
                {isExpanded && (() => {
                  const goals = sessionGoalChips(s)
                  const hasSegments = Array.isArray(s.segments) && s.segments.length > 0
                  return (
                    <div className="px-3 pb-3 pt-1 border-t border-dashed" style={{ borderColor: `${color}20` }}>
                      {!!s.description && (
                        <p className="text-sm text-gray-300 whitespace-pre-wrap">
                          {String(s.description)}
                        </p>
                      )}
                      <GoalChips chips={goals} className={clsx(!!s.description && 'mt-2')} />
                      {hasSegments && (
                        <div className="mt-2">
                          <SegmentSummary segments={s.segments as Segment[]} />
                        </div>
                      )}
                      {!s.description && goals.length === 0 && !hasSegments && (
                        <p className="text-sm text-gray-500">No description</p>
                      )}
                    </div>
                  )
                })()}
              </div>
            )
          })}
        </div>
      ) : (
        <div>
          <div className="text-xs text-gray-500">Nothing planned this week.</div>
        </div>
      )}

      {/* Pick the day to plan on rather than guessing one — every day of the
          week on screen is one click from its session form. */}
      <div className="mt-2.5">
        <div className="text-[10px] uppercase tracking-[0.12em] text-gray-500 mb-1.5">Add to</div>
        <div className="grid grid-cols-7 gap-1">
          {Array.from({ length: 7 }, (_, i) => i).map(offset => {
            const day = addDays(parseISO(weekStart), offset)
            const dateStr = format(day, 'yyyy-MM-dd')
            const isTodayCell = dateStr === todayStr
            const planned = (sessions ?? []).some(s => s.date === dateStr)
            return (
              <button
                key={dateStr}
                onClick={() => onPickDay(dateStr)}
                title={`Plan a session on ${format(day, 'EEEE, MMM d')}`}
                aria-label={`Plan a session on ${format(day, 'EEEE, MMM d')}`}
                className={clsx(
                  'flex flex-col items-center justify-center rounded-lg border py-1 min-h-[44px] transition-colors',
                  isTodayCell
                    ? 'border-blue-400/40 bg-blue-400/10 text-blue-300'
                    : 'border-surface-600 text-gray-400 hover:border-surface-500 hover:text-gray-100',
                )}
              >
                <span className="text-[9px] uppercase tracking-wider leading-none">{WEEKDAY_LETTERS[offset]}</span>
                <span className="text-xs font-mono tabular-nums font-semibold leading-tight mt-0.5">{format(day, 'd')}</span>
                <span className={clsx('w-1 h-1 rounded-full mt-0.5', planned ? 'bg-blue-400' : 'bg-transparent')} />
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/* ── Week Inspector ─────────────────────────────────
 * The selected week's numbers, sitting beside the grid instead of a screen
 * below it. Stacks under the grid below lg. */

interface WeekInspectorProps {
  weekStart: string
  report: WeeklyReport | undefined
  loading: boolean
  activities: Activity[] | undefined
  goals: GoalProgress[] | undefined
  /** Sessions planned inside this week. */
  planned: TrainingSession[] | undefined
  todayStr: string
  atCurrentWeek: boolean
  /** Week-over-week change per report key, as the stat cards used to show. */
  delta: (key: string) => number | string | null
  onPrev: () => void
  onNext: () => void
  onPickDay: (date: string) => void
}

const INSPECTOR_ACTIVITY_LIMIT = 6

export default function WeekInspector(props: WeekInspectorProps) {
  const {
    weekStart, report, loading, activities, goals, planned, todayStr,
    atCurrentWeek, delta, onPrev, onNext, onPickDay,
  } = props
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [showAll, setShowAll] = useState(false)

  const weeklyGoals = useMemo(
    () => (goals ?? []).filter(g => g.period === 'weekly'),
    [goals],
  )

  // Newest first, matching how the week reads in the grid above it.
  const sorted = useMemo(() => {
    const items = [...(activities ?? [])]
    items.sort((a, b) => (b.start_date_local ?? '').localeCompare(a.start_date_local ?? ''))
    return items
  }, [activities])
  const shown = showAll ? sorted : sorted.slice(0, INSPECTOR_ACTIVITY_LIMIT)
  const hidden = sorted.length - shown.length

  return (
    <aside className={clsx('panel p-4 flex flex-col gap-3.5 lg:sticky lg:top-4', isLight ? 'bg-white' : 'bg-surface-800')}>
      <header className="flex items-start justify-between gap-2">
        <div>
          <div className="eyebrow !text-blue-400">Week {format(parseISO(weekStart), 'w')}</div>
          <div className={clsx('text-[17px] font-semibold tracking-tight mt-0.5', isLight ? 'text-gray-900' : 'text-gray-100')}>
            {formatWeekRange(weekStart)}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={onPrev} className="btn !px-2.5" aria-label="Previous week">&larr;</button>
          <button onClick={onNext} disabled={atCurrentWeek} className="btn !px-2.5" aria-label="Next week">&rarr;</button>
          <ExportButton
            url={`/api/exports/weekly-report?week_start=${weekStart}`}
            label=""
            filename={`weekly_report_${weekStart}.png`}
            exportType="weekly-report"
          />
        </div>
      </header>

      {loading ? (
        <div className="grid grid-cols-2 gap-2 animate-pulse">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className={clsx('h-16 rounded-lg', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <InspectorKpi label="Distance" value={(report?.total_distance_km ?? 0).toFixed(1)} unit="km" delta={delta('total_distance_km')} />
          <InspectorKpi label="Time" value={formatDurationHM(Math.round((report?.total_time_hours ?? 0) * 3600))} delta={delta('total_time_hours')} />
          <InspectorKpi label="Activities" value={String(report?.total_activities ?? 0)} delta={delta('total_activities')} />
          <InspectorKpi label="Active days" value={String(report?.active_days ?? 0)} unit="/ 7" />
          <InspectorKpi label="Elevation" value={String(Math.round(report?.total_elevation_m ?? 0))} unit="m" delta={delta('total_elevation_m')} />
          <InspectorKpi label="Planned" value={String(planned?.length ?? 0)} unit="sessions" />
        </div>
      )}

      {weeklyGoals.length > 0 && (
        <section>
          <div className="eyebrow !text-[9px] mb-2">Weekly goals</div>
          <div className="space-y-2.5">
            {weeklyGoals.map(g => {
              const color = getSportColor(g.sport_type)
              const complete = g.percentage >= 100
              return (
                <div key={g.id}>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="flex items-center gap-1.5 min-w-0">
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                      <span className={clsx('text-[11px] truncate', isLight ? 'text-gray-700' : 'text-gray-300')}>
                        {g.sport_type === '__all__' ? 'All sports' : g.sport_type}
                      </span>
                    </span>
                    <span className="text-[11px] font-mono tabular-nums shrink-0" style={{ color: complete ? GOAL_DONE_COLOR : color }}>
                      {formatGoalProgress(g, g.current_value)}
                    </span>
                  </div>
                  <GoalProgressBar percentage={g.percentage} color={color} className="h-1.5" />
                </div>
              )
            })}
          </div>
        </section>
      )}

      <section>
        <div className="flex items-baseline justify-between mb-1">
          <span className="eyebrow !text-[9px]">Activities</span>
          <span className="text-[10px] font-mono tabular-nums text-gray-600">{sorted.length}</span>
        </div>
        {sorted.length === 0 ? (
          <div className="text-xs text-gray-500 py-1">Nothing logged this week.</div>
        ) : (
          <div>
            {shown.map(a => (
              <Link
                key={a.id}
                to={`/activities/${a.id}`}
                className={clsx(
                  'flex items-center gap-2 py-1.5 border-t first:border-t-0 group',
                  isLight ? 'border-gray-200' : 'border-surface-600',
                )}
              >
                <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: getSportColor(a.sport_type) }} />
                <span className={clsx(
                  'text-xs truncate flex-1',
                  isLight ? 'text-gray-600 group-hover:text-gray-900' : 'text-gray-300 group-hover:text-gray-100',
                )}>
                  {a.name}
                </span>
                {a.moving_time != null && (
                  <span className="text-[11px] font-mono tabular-nums text-gray-500 shrink-0">
                    {Math.round(a.moving_time / 60)}m
                  </span>
                )}
                <span className="text-[10px] font-mono text-gray-600 shrink-0 w-7 text-right">
                  {a.start_date_local ? format(parseLocalDate(a.start_date_local), 'EEE') : ''}
                </span>
              </Link>
            ))}
            {(hidden > 0 || showAll) && (
              <button
                onClick={() => setShowAll(v => !v)}
                className={clsx(
                  'w-full text-center text-[11px] font-medium py-1.5 border-t text-blue-400 hover:text-blue-300',
                  isLight ? 'border-gray-200' : 'border-surface-600',
                )}
              >
                {showAll ? 'Show less' : `Show ${hidden} more`}
              </button>
            )}
          </div>
        )}
      </section>

      <div className={clsx('mt-auto pt-3 border-t border-dashed', isLight ? 'border-gray-300' : 'border-surface-500')}>
        <PlannedSessions sessions={planned} todayStr={todayStr} weekStart={weekStart} onPickDay={onPickDay} />
      </div>
    </aside>
  )
}

function InspectorKpi({ label, value, unit, delta }: {
  label: string
  value: string
  unit?: string
  delta?: number | string | null
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const up = delta === 'new' || (typeof delta === 'number' && delta >= 0)
  // A change that rounds to zero reads as "-0%", which says nothing.
  const showDelta = delta === 'new' || (typeof delta === 'number' && Math.abs(delta) >= 0.5)
  return (
    <div className={clsx('rounded-lg border px-3 py-2.5', isLight ? 'bg-gray-50 border-gray-200' : 'bg-surface-700/60 border-surface-600')}>
      <div className="text-[10px] uppercase tracking-[0.12em] text-gray-500 mb-1">{label}</div>
      <div className="flex items-baseline gap-1.5">
        <span className={clsx('text-xl font-bold font-mono tabular-nums tracking-tight', isLight ? 'text-gray-900' : 'text-gray-100')}>
          {value}
          {unit && <span className="text-[11px] font-medium text-gray-500 ml-1">{unit}</span>}
        </span>
        {showDelta && (
          <span className={clsx(
            'text-[10px] font-semibold shrink-0',
            up ? (isLight ? 'text-green-700' : 'text-green-400') : (isLight ? 'text-red-700' : 'text-red-400'),
          )}>
            {delta === 'new' ? 'new' : `${(delta as number) >= 0 ? '+' : ''}${(delta as number).toFixed(0)}%`}
          </span>
        )}
      </div>
    </div>
  )
}
