import {
  useState, useMemo, useRef, useEffect, useCallback, lazy, Suspense,
  type DragEvent as ReactDragEvent, type ReactNode,
} from 'react'
import {
  startOfMonth, endOfMonth, eachDayOfInterval, format, addMonths, subMonths, addDays, subDays,
  isSameMonth, isToday, startOfWeek, endOfWeek, isSameWeek, parseISO, differenceInCalendarDays,
} from 'date-fns'
import { Link } from 'react-router-dom'
import {
  useActivitiesByDateRange, useCalendarSessionsByRange, useCreateSession, useUpdateSession,
  useDeleteSession, useWeeklyReport, useAthleteZones, useStreaks, useGoalProgress, useGoals,
  useSessionScores, usePlanAccomplishment, useRaceEventsByRange, useUpcomingRaces,
  useCreateRaceEvent, useUpdateRaceEvent, useDeleteRaceEvent, useActivities, type Activity,
  type ExecutionScore, type Goal, type GoalMetric, type GoalProgress, type RaceEvent,
  type SessionScoresResponse, type TrainingSession, type WeeklyReport,
} from '../api/hooks'
import { getSportColor, DEFAULT_SPORT_COLOR } from '../constants/sportColors'
import { getPaceUnit, formatDist, formatPace, isSpeedSport, formatDurationHM, formatDistExact } from '../utils/formatSpeed'
import { localDateStr, parseLocalDate } from '../utils/dates'
import { scoreColor } from '../utils/scoreColor'
import { WEEKDAYS_SHORT, WEEKDAYS_MIN, WEEKDAY_LETTERS } from '../constants/weekdays'
import ExportButton from '../components/shared/ExportButton'
import { FlagIcon, CheckIcon, DistanceIcon, TimerIcon, BoltIcon, RangeIcon, HeartIcon } from '../components/icons'
import clsx from 'clsx'
import { useTheme } from '../hooks/useTheme'
import { useToast } from '../hooks/useToast'
import { SegmentSummary, type Segment } from '../components/shared/SegmentListBuilder'

// Recharts and the day editor load on demand: the calendar paints without them
const WeekDetailCharts = lazy(() => import('../components/calendar/WeekDetailCharts'))
const SessionModal = lazy(() => import('../components/calendar/SessionModal'))

/** Dots that fit across a day cell on the compact mobile grid before overflowing to a "+n". */
const MOBILE_DOT_LIMIT = 4

type CalendarView = 'month' | 'week'

const VIEW_STORAGE_KEY = 'calendar-view'

/** Week view is the only legible default on a phone — below md the month grid
 *  collapses to dots, which can't carry a session's name or its targets. */
function getInitialView(): CalendarView {
  const stored = localStorage.getItem(VIEW_STORAGE_KEY)
  if (stored === 'month' || stored === 'week') return stored
  return window.matchMedia('(max-width: 767px)').matches ? 'week' : 'month'
}

/** Label a Monday-anchored week, dropping the repeated month when it doesn't change. */
function formatWeekRange(weekStart: string): string {
  const start = parseISO(weekStart)
  const end = addDays(start, 6)
  return isSameMonth(start, end)
    ? `${format(start, 'MMM d')} – ${format(end, 'd')}`
    : `${format(start, 'MMM d')} – ${format(end, 'MMM d')}`
}

/** Whether a day's planned sessions were all covered by logged activities.
 *  Null for future days, where "missed" would be premature. */
function dayPlanStatus(
  sessions: TrainingSession[],
  activities: Activity[],
  isPastOrToday: boolean,
): 'done' | 'missed' | null {
  if (sessions.length === 0 || !isPastOrToday) return null
  const activitySports = new Set(activities.map(a => a.sport_type))
  const allMatched = sessions.every(s => {
    if (s.sport_type.toLowerCase() === 'rest') return activities.length === 0
    return activitySports.has(s.sport_type)
  })
  return allMatched ? 'done' : 'missed'
}

function dayAvgScore(
  sessions: TrainingSession[],
  scores: SessionScoresResponse | undefined,
): number | null {
  const scored = sessions
    .map(s => scores?.[String(s.id)])
    .filter((sc): sc is ExecutionScore => sc != null && sc.overall_score != null)
  if (scored.length === 0) return null
  return Math.round(scored.reduce((sum, sc) => sum + sc.overall_score, 0) / scored.length)
}

interface GoalChip {
  icon: ReactNode
  color: string
  label: string
}

const GOAL_METRIC_VALUE: Record<GoalMetric, (a: Activity) => number> = {
  distance_km: a => a.distance_km ?? 0,
  time_hours: a => (a.moving_time ?? 0) / 3600,
  activities: () => 1,
  elevation_m: a => a.total_elevation_gain ?? 0,
}

interface WeekSummary {
  totalKm: number
  timeStr: string
  plannedKm: number
  /** False for a week with nothing logged or planned — its totals row is noise. */
  hasContent: boolean
  goals: (Goal & { current_value: number; percentage: number })[]
}

/** Week totals and weekly-goal progress, shared by the month grid's per-week
 *  divider and the week view's panel header. */
function WeekTotals({ summary, className }: { summary: WeekSummary; className?: string }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  return (
    <div className={clsx('flex items-center flex-wrap gap-x-3 gap-y-1', className)}>
      {summary.goals.map(g => {
        const color = g.sport_type === '__all__' ? DEFAULT_SPORT_COLOR : getSportColor(g.sport_type)
        const complete = g.percentage >= 100
        return (
          <div
            key={g.id}
            className="flex items-center gap-1"
            title={`${g.sport_type === '__all__' ? 'All' : g.sport_type}: ${g.current_value.toFixed(1)} / ${g.target_value} ${g.metric.replace('_', ' ')} (${g.percentage.toFixed(0)}%)`}
          >
            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
            <div className={clsx('w-16 h-1.5 rounded-full overflow-hidden', isLight ? 'bg-gray-200' : 'bg-surface-700')}>
              <div className="h-full rounded-full" style={{ width: `${Math.min(g.percentage, 100)}%`, backgroundColor: complete ? '#22c55e' : color }} />
            </div>
            <span className="text-[9px] font-mono" style={{ color: complete ? '#22c55e' : '#6b7280' }}>
              {g.percentage.toFixed(0)}%
            </span>
          </div>
        )
      })}
      <span className="text-[10px] text-gray-500 font-mono tabular-nums">{summary.totalKm.toFixed(1)} km</span>
      <span className="text-[10px] text-gray-500 font-mono tabular-nums">{summary.timeStr}</span>
      {summary.plannedKm > 0 && (
        <span className="text-[10px] text-gray-500 font-mono tabular-nums opacity-70">
          plan {summary.plannedKm.toFixed(1)} km
        </span>
      )}
    </div>
  )
}

/** A planned session's targets, in the same order and colors as the goal cards
 *  in the session modal. */
function sessionGoalChips(s: TrainingSession): GoalChip[] {
  const chips: GoalChip[] = []
  const hasSegments = Array.isArray(s.segments) && s.segments.length > 0
  // Distance auto-derived from segments would just restate the workout below it.
  if (s.planned_distance_km != null && !hasSegments) {
    chips.push({ icon: <DistanceIcon size={10} />, color: '#3b82f6', label: formatDist(s.planned_distance_km, s.sport_type) })
  }
  if (s.planned_duration_mins != null) {
    chips.push({ icon: <TimerIcon size={10} />, color: '#22c55e', label: `${s.planned_duration_mins} min` })
  }
  const useSpeed = isSpeedSport(s.sport_type)
  const paceUnit = getPaceUnit(s.sport_type)
  if (s.target_avg_pace != null) {
    chips.push({ icon: <BoltIcon size={10} />, color: '#f97316', label: `${formatPace(s.target_avg_pace, useSpeed)} ${paceUnit}` })
  }
  if (s.target_pace_min != null || s.target_pace_max != null) {
    const isPace = paceUnit === 'min/km'
    const parts: string[] = []
    if (s.target_pace_min != null) parts.push(`${isPace ? 'fastest' : 'min'} ${formatPace(s.target_pace_min, useSpeed)}`)
    if (s.target_pace_max != null) parts.push(`${isPace ? 'slowest' : 'max'} ${formatPace(s.target_pace_max, useSpeed)}`)
    chips.push({ icon: <RangeIcon size={10} />, color: '#a855f7', label: `${parts.join(' – ')} ${paceUnit}` })
  }
  if (s.target_hr_zone != null) {
    chips.push({ icon: <HeartIcon size={10} />, color: '#ef4444', label: `Zone ${s.target_hr_zone} @ ${s.target_zone_pct ?? 80}%` })
  }
  return chips
}

function GoalChips({ chips, className }: { chips: GoalChip[]; className?: string }) {
  if (chips.length === 0) return null
  return (
    <div className={clsx('flex flex-wrap gap-1.5', className)}>
      {chips.map((g, i) => (
        <span
          key={i}
          className="text-[11px] rounded-full px-2 py-0.5 border font-mono tabular-nums inline-flex items-center gap-1.5"
          style={{ color: g.color, borderColor: `${g.color}40`, backgroundColor: `${g.color}10` }}
        >
          {g.icon} {g.label}
        </span>
      ))}
    </div>
  )
}

/* ── Streak badge — current or best, with uppercase label ──────── */
function StreakBadge({ value, label, kind, title }: { value: number; label: string; kind: 'current' | 'best'; title?: string }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const accent = kind === 'best'
    ? (isLight ? '#b45309' : '#fbbf24') // amber
    : (isLight ? '#111827' : '#f3f4f6') // neutral strong
  return (
    <div
      className={clsx(
        'panel flex items-center gap-1.5 px-2.5 py-1',
        isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
      )}
      title={title}
    >
      {kind === 'best' ? (
        <svg width="11" height="11" viewBox="0 0 16 16" fill="none" className="shrink-0" aria-hidden="true">
          <path d="M9 1.5L4 9h4l-1 5.5L12 7H8z" fill={accent} />
        </svg>
      ) : (
        <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke={accent} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="shrink-0" aria-hidden="true">
          <circle cx="10" cy="3" r="1.5" fill={accent} stroke="none" />
          <path d="M5 7l3-1.5 2 2.5 2-1M4 10l3 1 1.5-2M6 12.5l1 2.5M9.5 10l1 5" />
        </svg>
      )}
      <span className="text-xs font-mono tabular-nums font-semibold" style={{ color: accent }}>{value}</span>
      <span className="eyebrow text-[9px]">{label}</span>
    </div>
  )
}




/* ── Plan accomplishment badge — % of planned sessions executed ── */
function PlanRateBadge({ rate, label, title }: { rate: number; label: string; title?: string }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const accent = scoreColor(rate)
  return (
    <div
      className={clsx(
        'panel flex items-center gap-1.5 px-2.5 py-1',
        isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
      )}
      title={title}
    >
      <span style={{ color: accent }}><CheckIcon size={11} /></span>
      <span className="text-xs font-mono tabular-nums font-semibold" style={{ color: accent }}>
        {Math.round(rate)}%
      </span>
      <span className="eyebrow text-[9px]">{label}</span>
    </div>
  )
}


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

function WeekInspector(props: WeekInspectorProps) {
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
              const color = g.sport_type === '__all__' ? DEFAULT_SPORT_COLOR : getSportColor(g.sport_type)
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
                    <span className="text-[11px] font-mono tabular-nums shrink-0" style={{ color: complete ? '#22c55e' : color }}>
                      {g.current_value.toFixed(1)} / {g.target_value}
                    </span>
                  </div>
                  <div className={clsx('h-1.5 rounded-full overflow-hidden', isLight ? 'bg-gray-200' : 'bg-surface-700')}>
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${Math.min(g.percentage, 100)}%`, backgroundColor: complete ? '#22c55e' : color }}
                    />
                  </div>
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

/* ── Week Picker ──────────────────────────────────── */
function WeekPicker({ currentWeekStart, onSelect, onClose }: {
  currentWeekStart: string
  onSelect: (weekStart: string) => void
  onClose: () => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const ref = useRef<HTMLDivElement>(null)
  const [viewMonth, setViewMonth] = useState(() => {
    try { return startOfMonth(parseISO(currentWeekStart)) }
    catch { return startOfMonth(new Date()) }
  })

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  const mStart = startOfMonth(viewMonth)
  const mEnd = endOfMonth(viewMonth)
  const calStart = startOfWeek(mStart, { weekStartsOn: 1 })
  const calEnd = endOfWeek(mEnd, { weekStartsOn: 1 })
  const days = eachDayOfInterval({ start: calStart, end: calEnd })

  const selectedMonday = (() => {
    try { return parseISO(currentWeekStart) }
    catch { return startOfWeek(new Date(), { weekStartsOn: 1 }) }
  })()

  return (
    <div ref={ref} className={clsx(
      'absolute top-full mt-1 z-50 rounded-xl p-3 shadow-xl w-[260px] border',
      isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
    )}>
      <div className="flex items-center justify-between mb-2">
        <button onClick={() => setViewMonth(m => subMonths(m, 1))} className={clsx('px-1', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-400 hover:text-gray-100')}>&larr;</button>
        <span className={clsx('text-xs font-medium', isLight ? 'text-gray-700' : 'text-gray-300')}>{format(viewMonth, 'MMMM yyyy')}</span>
        <button onClick={() => setViewMonth(m => addMonths(m, 1))} className={clsx('px-1', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-400 hover:text-gray-100')}>&rarr;</button>
      </div>
      <div className="grid grid-cols-7 text-center mb-1 gap-px">
        {WEEKDAYS_MIN.map(d => <span key={d} className="eyebrow text-[9px]">{d}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-px">
        {days.map(day => {
          const monday = startOfWeek(day, { weekStartsOn: 1 })
          const isSelected = isSameWeek(day, selectedMonday, { weekStartsOn: 1 })
          const isCurrent = isSameWeek(day, new Date(), { weekStartsOn: 1 })
          const inMonth = isSameMonth(day, viewMonth)
          return (
            <button
              key={day.toISOString()}
              onClick={() => {
                onSelect(format(monday, 'yyyy-MM-dd'))
                onClose()
              }}
              className={clsx(
                'text-[11px] py-1 rounded transition-colors',
                isSelected
                  ? isLight ? 'bg-gray-900/10 text-gray-900 font-bold' : 'bg-gray-400/20 text-gray-100 font-bold'
                  : isCurrent
                    ? isLight ? 'bg-gray-100 text-gray-700' : 'bg-surface-600 text-gray-300'
                    : inMonth
                      ? isLight ? 'text-gray-600 hover:bg-gray-100' : 'text-gray-400 hover:bg-surface-700'
                      : isLight ? 'text-gray-300 hover:bg-gray-50' : 'text-gray-600 hover:bg-surface-700',
              )}
            >
              {format(day, 'd')}
            </button>
          )
        })}
      </div>
      <button
        onClick={() => {
          onSelect(format(startOfWeek(new Date(), { weekStartsOn: 1 }), 'yyyy-MM-dd'))
          onClose()
        }}
        className={clsx(
          'mt-2 w-full text-[11px] py-1 rounded transition-colors',
          isLight ? 'text-gray-500 hover:text-gray-800 bg-gray-100 hover:bg-gray-200' : 'text-gray-400 hover:text-gray-100 bg-surface-700',
        )}
      >
        This week
      </button>
    </div>
  )
}

/* ── Month Picker ─────────────────────────────────── */
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function MonthPicker({ current, onSelect, onClose }: {
  current: Date
  onSelect: (d: Date) => void
  onClose: () => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const ref = useRef<HTMLDivElement>(null)
  const [viewYear, setViewYear] = useState(current.getFullYear())
  const nowMonth = new Date().getMonth()
  const nowYear = new Date().getFullYear()

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  return (
    <div ref={ref} className={clsx(
      'absolute top-full mt-1 z-50 rounded-xl p-3 shadow-xl w-[220px] border',
      isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
    )}>
      <div className="flex items-center justify-between mb-2">
        <button onClick={() => setViewYear(y => y - 1)} className={clsx('px-1', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-400 hover:text-gray-100')}>&larr;</button>
        <span className={clsx('text-xs font-medium', isLight ? 'text-gray-700' : 'text-gray-300')}>{viewYear}</span>
        <button onClick={() => setViewYear(y => y + 1)} className={clsx('px-1', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-400 hover:text-gray-100')}>&rarr;</button>
      </div>
      <div className="grid grid-cols-3 gap-1">
        {MONTH_NAMES.map((name, i) => {
          const isSelected = current.getFullYear() === viewYear && current.getMonth() === i
          const isCurrent = nowYear === viewYear && nowMonth === i
          return (
            <button
              key={name}
              onClick={() => { onSelect(new Date(viewYear, i, 1)); onClose() }}
              className={clsx(
                'text-[11px] py-1.5 rounded transition-colors',
                isSelected
                  ? isLight ? 'bg-gray-900/10 text-gray-900 font-bold' : 'bg-gray-400/20 text-gray-100 font-bold'
                  : isCurrent
                    ? isLight ? 'bg-gray-100 text-gray-700' : 'bg-surface-600 text-gray-300'
                    : isLight ? 'text-gray-600 hover:bg-gray-100' : 'text-gray-400 hover:bg-surface-700',
              )}
            >
              {name}
            </button>
          )
        })}
      </div>
      <button
        onClick={() => { onSelect(new Date(nowYear, nowMonth, 1)); onClose() }}
        className={clsx(
          'mt-2 w-full text-[11px] py-1 rounded transition-colors',
          isLight ? 'text-gray-500 hover:text-gray-800 bg-gray-100 hover:bg-gray-200' : 'text-gray-400 hover:text-gray-100 bg-surface-700',
        )}
      >
        This month
      </button>
    </div>
  )
}

/* ── Week View ──────────────────────────────────────── */
interface DayDropProps {
  onDragOver: (e: ReactDragEvent) => void
  onDragLeave: () => void
  onDrop: (e: ReactDragEvent) => void
}

interface WeekViewProps {
  days: Date[]
  summary: WeekSummary | undefined
  activityMap: Record<string, Activity[]>
  sessionMap: Record<string, TrainingSession[]>
  raceMap: Record<string, RaceEvent[]>
  scores: SessionScoresResponse | undefined
  dragOverDate: string | null
  draggingSessionId: number | null
  dayDropProps: (dateStr: string, day: Date) => DayDropProps
  onOpenDay: (dateStr: string) => void
  onSessionDragStart: (e: ReactDragEvent, session: TrainingSession) => void
  onSessionDragEnd: () => void
  onRaceDragStart: (e: ReactDragEvent, race: RaceEvent) => void
}

/** One full-width row per day. Sessions are day-scoped, so a time grid would
 *  imply an ordering the data doesn't carry — the rows stay a plain list. */
function WeekView({
  days, summary, activityMap, sessionMap, raceMap, scores, dragOverDate, draggingSessionId,
  dayDropProps, onOpenDay, onSessionDragStart, onSessionDragEnd, onRaceDragStart,
}: WeekViewProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const endOfToday = new Date(new Date().setHours(23, 59, 59, 999))

  return (
    <div
      className={clsx(
        'rounded-xl border overflow-hidden divide-y',
        isLight ? 'bg-white border-gray-200 divide-gray-200' : 'bg-surface-800 border-surface-600 divide-surface-600',
      )}
      style={{ animation: 'fadeIn 200ms ease-out' }}
    >
      {summary?.hasContent && (
        <WeekTotals
          summary={summary}
          className={clsx('px-2.5 py-2', isLight ? 'bg-gray-50/80' : 'bg-surface-900/40')}
        />
      )}
      {days.map(day => {
        const dateStr = format(day, 'yyyy-MM-dd')
        const dayActivities = activityMap[dateStr] ?? []
        const daySessions = sessionMap[dateStr] ?? []
        const dayRaces = raceMap[dateStr] ?? []
        const today = isToday(day)
        const planStatus = dayPlanStatus(daySessions, dayActivities, day <= endOfToday)
        const avgScore = planStatus ? dayAvgScore(daySessions, scores) : null
        const isEmpty = dayActivities.length + daySessions.length + dayRaces.length === 0

        return (
          <div
            key={dateStr}
            {...dayDropProps(dateStr, day)}
            className={clsx(
              'flex items-stretch gap-3 p-2 md:p-2.5 transition-colors',
              today && (isLight ? 'bg-gray-50' : 'bg-white/[0.02]'),
              dragOverDate === dateStr && 'ring-1 ring-inset ring-gray-400/40 bg-gray-400/[0.04]',
            )}
          >
            <button
              onClick={() => onOpenDay(dateStr)}
              className={clsx(
                'shrink-0 w-12 md:w-14 text-left rounded-lg px-1.5 py-1 transition-colors',
                isLight ? 'hover:bg-black/[0.05]' : 'hover:bg-white/[0.06]',
              )}
              aria-label={`Open ${format(day, 'EEEE, MMMM d')}`}
            >
              <div className="eyebrow !text-[9px]">{format(day, 'EEE')}</div>
              <div
                className={clsx(
                  'font-mono tabular-nums text-lg leading-none mt-0.5',
                  today ? (isLight ? 'text-gray-900 font-semibold' : 'text-gray-100 font-semibold') : 'text-gray-400',
                )}
                style={{ letterSpacing: '-0.02em' }}
              >
                {format(day, 'd')}
              </div>
              {today && <div className="eyebrow !text-[8px] mt-1">today</div>}
            </button>

            <div className="flex-1 min-w-0 space-y-1">
              {dayRaces.map(r => (
                <div
                  key={`race-${r.id}`}
                  draggable
                  onDragStart={e => onRaceDragStart(e, r)}
                  onClick={() => onOpenDay(dateStr)}
                  className="w-fit max-w-full rounded-lg border px-2.5 py-1.5 cursor-grab active:cursor-grabbing border-amber-500/50 bg-amber-500/[0.06] transition-colors hover:border-amber-500/70"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-amber-500 shrink-0"><FlagIcon size={10} /></span>
                    <span className="text-xs font-medium text-amber-500">{r.name}</span>
                    {r.distance_km != null && (
                      <span className="text-[11px] font-mono tabular-nums text-gray-400">{formatDistExact(r.distance_km, r.sport_type)}</span>
                    )}
                    {!!r.location && <span className="text-[11px] text-gray-500 truncate">{r.location}</span>}
                  </div>
                </div>
              ))}

              {dayActivities.map(a => {
                const color = getSportColor(a.sport_type)
                return (
                  <Link
                    key={a.id}
                    to={`/activities/${a.id}`}
                    className={clsx(
                      'flex items-center gap-2 rounded-lg px-2.5 py-1.5 group transition-colors',
                      isLight ? 'hover:bg-black/[0.04]' : 'hover:bg-white/[0.04]',
                    )}
                  >
                    <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                    <span className={clsx('text-xs truncate flex-1', isLight ? 'text-gray-600 group-hover:text-gray-900' : 'text-gray-300 group-hover:text-gray-100')}>
                      {a.name}
                    </span>
                    {/* Gym and similar log 0 km — the unit is noise there. */}
                    {!!a.distance_km && (
                      <span className="text-[11px] font-mono tabular-nums shrink-0" style={{ color }}>
                        {formatDist(a.distance_km, a.sport_type)}
                      </span>
                    )}
                    {a.moving_time != null && (
                      <span className="text-[11px] font-mono tabular-nums text-gray-500 shrink-0">
                        {formatDurationHM(a.moving_time)}
                      </span>
                    )}
                  </Link>
                )
              })}

              {daySessions.map(s => {
                const color = getSportColor(s.sport_type)
                const score = scores?.[String(s.id)]
                const hasSegments = Array.isArray(s.segments) && s.segments.length > 0
                return (
                  <div
                    key={s.id}
                    draggable
                    onDragStart={e => onSessionDragStart(e, s)}
                    onDragEnd={onSessionDragEnd}
                    onClick={() => onOpenDay(dateStr)}
                    className={clsx(
                      // Hugs its content so a bare sport tag doesn't stretch into an
                      // empty band the width of the row.
                      'w-fit max-w-full rounded-lg border border-dashed px-2.5 py-1.5',
                      'cursor-grab active:cursor-grabbing transition-all duration-150',
                      draggingSessionId === s.id && 'opacity-40 scale-[0.98]',
                    )}
                    style={{ borderColor: `${color}55`, backgroundColor: `${color}0a` }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                      <span className="text-xs font-medium shrink-0" style={{ color }}>{s.sport_type}</span>
                      {!!s.description && (
                        <span className="text-xs text-gray-400 truncate">{s.description}</span>
                      )}
                      {score?.overall_score != null && (
                        <span
                          className="ml-auto shrink-0 text-[11px] font-mono tabular-nums font-bold px-1.5 rounded"
                          style={{ color: scoreColor(score.overall_score), backgroundColor: `${scoreColor(score.overall_score)}18` }}
                        >
                          {score.overall_score}
                        </span>
                      )}
                    </div>
                    <GoalChips chips={sessionGoalChips(s)} className="mt-1.5" />
                    {hasSegments && (
                      <div className="mt-1.5">
                        <SegmentSummary segments={s.segments as Segment[]} />
                      </div>
                    )}
                  </div>
                )
              })}

              {isEmpty && (
                <button
                  onClick={() => onOpenDay(dateStr)}
                  className={clsx(
                    'w-full text-left text-xs rounded-lg px-2.5 py-1.5 transition-colors',
                    isLight ? 'text-gray-400 hover:text-gray-700 hover:bg-black/[0.03]' : 'text-gray-600 hover:text-gray-300 hover:bg-white/[0.03]',
                  )}
                >
                  Nothing planned — add a session
                </button>
              )}
            </div>

            {planStatus && (
              <div className="shrink-0 flex items-start gap-1.5 pt-1.5">
                {avgScore !== null && (
                  <span
                    className="text-[10px] font-bold font-mono tabular-nums px-1 rounded"
                    style={{ color: scoreColor(avgScore), backgroundColor: `${scoreColor(avgScore)}15` }}
                  >
                    {avgScore}
                  </span>
                )}
                <span
                  className={clsx('w-2 h-2 rounded-full mt-1', planStatus === 'done' ? 'bg-green-400' : 'bg-red-400')}
                  title={planStatus === 'done' ? 'Plan completed' : 'Plan missed'}
                />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ── Calendar Page ──────────────────────────────────── */
export default function CalendarPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()
  const [view, setView] = useState<CalendarView>(getInitialView)
  const [currentMonth, setCurrentMonth] = useState(new Date())
  const thisWeekStart = format(startOfWeek(new Date(), { weekStartsOn: 1 }), 'yyyy-MM-dd')

  // The current week is empty for most of its first days, which left the whole
  // report reading as zeros. Until the athlete picks a week, follow the last one
  // that actually has activity — which is the current week once they train in it.
  const { data: newestActivity } = useActivities(1, 1)
  const latestActiveWeek = useMemo(() => {
    const newest = newestActivity?.items?.[0]?.start_date_local
    if (!newest) return null
    return format(startOfWeek(parseLocalDate(newest), { weekStartsOn: 1 }), 'yyyy-MM-dd')
  }, [newestActivity])

  const [pickedWeek, setPickedWeek] = useState<string | null>(null)
  const weekStart = pickedWeek ?? latestActiveWeek ?? thisWeekStart

  const [sportFilter, setSportFilter] = useState<Set<string>>(new Set())
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)
  const [showMonthPicker, setShowMonthPicker] = useState(false)
  const [showWeekPicker, setShowWeekPicker] = useState(false)
  const [draggingSessionId, setDraggingSessionId] = useState<number | null>(null)
  const [draggingSession, setDraggingSession] = useState<TrainingSession | null>(null)
  const [dragOverDate, setDragOverDate] = useState<string | null>(null)

  useEffect(() => { localStorage.setItem(VIEW_STORAGE_KEY, view) }, [view])

  const showToast = useCallback((msg: string) => {
    toast(msg, 'success')
  }, [toast])

  const { data: streakData } = useStreaks()
  const { data: planRate } = usePlanAccomplishment()

  // Monday-aligned range for whichever view is active, memoized so week summaries
  // don't recompute on drag&drop re-renders.
  const { days, dateFrom, dateTo } = useMemo(() => {
    if (view === 'week') {
      const start = parseISO(weekStart)
      const end = addDays(start, 6)
      return {
        days: eachDayOfInterval({ start, end }),
        dateFrom: weekStart,
        dateTo: format(end, 'yyyy-MM-dd'),
      }
    }
    const calStart = startOfWeek(startOfMonth(currentMonth), { weekStartsOn: 1 })
    const calEnd = endOfWeek(endOfMonth(currentMonth), { weekStartsOn: 1 })
    return {
      days: eachDayOfInterval({ start: calStart, end: calEnd }),
      dateFrom: format(calStart, 'yyyy-MM-dd'),
      dateTo: format(calEnd, 'yyyy-MM-dd'),
    }
  }, [view, weekStart, currentMonth])

  // Yearly goals track the range on screen, so week-view navigation across a
  // year boundary still resolves the right targets.
  const { data: calGoals } = useGoals(parseISO(dateFrom).getFullYear())

  /** Switching views carries the date context over rather than snapping to today. */
  const switchView = useCallback((next: CalendarView) => {
    setView(prev => {
      if (prev === next) return prev
      if (next === 'week') {
        // The month grid highlights a selected week; keep it rather than snapping
        // away from it, and only fall back when it isn't in the month on screen.
        const gridStart = startOfWeek(startOfMonth(currentMonth), { weekStartsOn: 1 })
        const gridEnd = endOfWeek(endOfMonth(currentMonth), { weekStartsOn: 1 })
        const selected = parseISO(weekStart)
        if (selected < gridStart || selected > gridEnd) {
          const target = isSameMonth(currentMonth, new Date())
            ? startOfWeek(new Date(), { weekStartsOn: 1 })
            : gridStart
          setPickedWeek(format(target, 'yyyy-MM-dd'))
        }
      } else {
        setCurrentMonth(startOfMonth(parseISO(weekStart)))
      }
      return next
    })
    setShowMonthPicker(false)
    setShowWeekPicker(false)
  }, [currentMonth, weekStart])

  const { data: activitiesData, isLoading: activitiesLoading } = useActivitiesByDateRange(dateFrom, dateTo)
  // Fetch the full grid range so sessions on leading/trailing days of adjacent months render too
  const { data: sessions } = useCalendarSessionsByRange(dateFrom, dateTo)
  const { data: sessionScores } = useSessionScores(dateFrom, dateTo)
  const createSession = useCreateSession()
  const updateSession = useUpdateSession()
  const deleteSession = useDeleteSession()
  const { data: raceEventsRange } = useRaceEventsByRange(dateFrom, dateTo)
  const { data: upcomingRaces } = useUpcomingRaces()
  const createRace = useCreateRaceEvent()
  const updateRace = useUpdateRaceEvent()
  const deleteRace = useDeleteRaceEvent()

  // Weekly report — in week view the grid's own selector drives `weekStart`,
  // so the report always describes the week on screen.
  const isCurrentWeek = weekStart === thisWeekStart
  const { data: weekData, isLoading: weekLoading } = useWeeklyReport(weekStart)
  const { data: athleteZones } = useAthleteZones()
  const hrZoneBounds = athleteZones?.heart_rate?.zones ?? undefined
  const current = weekData?.current
  const previous = weekData?.previous

  // weekStart is always a Monday (the backend snaps to Monday too), so the range is known
  // locally and this query can fire in parallel with the weekly report
  const weekEndStr = format(addDays(parseISO(weekStart), 6), 'yyyy-MM-dd')
  const { data: weekActivities } = useActivitiesByDateRange(weekStart, weekEndStr)
  const { data: goalProgressData } = useGoalProgress(weekStart)

  // Sessions planned in the week being inspected. Keyed on the week rather than
  // the grid's range so it stays right when the month moves off that week.
  const todayStr = format(new Date(), 'yyyy-MM-dd')
  const { data: weekPlanned } = useCalendarSessionsByRange(weekStart, weekEndStr)

  // Shared sport color map for weekly section
  const weekDetailSkeleton = (
    <div className="space-y-4">
      <div className={clsx('rounded-xl h-56 border animate-pulse', isLight ? 'bg-gray-100 border-gray-200' : 'bg-surface-800 border-surface-600')} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className={clsx('rounded-xl h-48 border animate-pulse', isLight ? 'bg-gray-100 border-gray-200' : 'bg-surface-800 border-surface-600')} />
        <div className={clsx('rounded-xl h-48 border animate-pulse', isLight ? 'bg-gray-100 border-gray-200' : 'bg-surface-800 border-surface-600')} />
      </div>
    </div>
  )
  const weekSportColors = useMemo(() => {
    const map: Record<string, string> = {}
    if (!current?.distance_per_sport_km) return map
    Object.keys(current.distance_per_sport_km).forEach(sport => {
      map[sport] = getSportColor(sport)
    })
    return map
  }, [current])

  function delta(key: string): number | string | null {
    if (!current || !previous) return null
    const c = (current as unknown as Record<string, unknown>)[key]
    const p = (previous as unknown as Record<string, unknown>)[key]
    if (c == null || c === 0) return null
    if (!p || p === 0) return 'new'
    if (typeof c !== 'number' || typeof p !== 'number') return null
    return ((c - p) / p) * 100
  }

  // Sport filter — an empty set means "all". Options come from the unfiltered
  // range, unioned with the active selection so a sport that's absent from the
  // range being viewed still has a chip to switch off.
  const sportChips = useMemo(() => {
    const set = new Set<string>(sportFilter)
    activitiesData?.items?.forEach(a => set.add(a.sport_type))
    sessions?.forEach(s => set.add(s.sport_type))
    raceEventsRange?.forEach(r => set.add(r.sport_type))
    return [...set].sort()
  }, [activitiesData, sessions, raceEventsRange, sportFilter])

  const showSport = useCallback(
    (sport: string) => sportFilter.size === 0 || sportFilter.has(sport),
    [sportFilter],
  )

  const toggleSport = useCallback((sport: string) => {
    setSportFilter(prev => {
      const next = new Set(prev)
      if (!next.delete(sport)) next.add(sport)
      return next
    })
  }, [])

  // Build maps
  const activityMap = useMemo(() => {
    const map: Record<string, Activity[]> = {}
    if (activitiesData?.items) {
      for (const a of activitiesData.items) {
        if (!showSport(a.sport_type)) continue
        const dateStr = a.start_date_local ? localDateStr(a.start_date_local) : null
        if (dateStr) {
          if (!map[dateStr]) map[dateStr] = []
          map[dateStr].push(a)
        }
      }
    }
    return map
  }, [activitiesData, showSport])

  const sessionMap = useMemo(() => {
    const map: Record<string, TrainingSession[]> = {}
    if (sessions) {
      for (const s of sessions) {
        if (!showSport(s.sport_type)) continue
        if (!map[s.date]) map[s.date] = []
        map[s.date].push(s)
      }
    }
    return map
  }, [sessions, showSport])

  const raceMap = useMemo(() => {
    const map: Record<string, RaceEvent[]> = {}
    if (raceEventsRange) {
      for (const r of raceEventsRange) {
        if (!showSport(r.sport_type)) continue
        if (!map[r.date]) map[r.date] = []
        map[r.date].push(r)
      }
    }
    return map
  }, [raceEventsRange, showSport])

  // One entry per week row (keyed by the index of its Monday in `days`); memoized so
  // km/time totals and goal bars don't recompute on every dragOver re-render
  const weekSummaries = useMemo(() => {
    const summaries: Record<number, WeekSummary> = {}
    // A filtered-out sport's goal would sit at a permanent 0% — drop it rather
    // than report progress against activities the grid is hiding.
    const weeklyGoals = (calGoals ?? []).filter(
      g => g.period === 'weekly' && (g.sport_type === '__all__' || showSport(g.sport_type)),
    )
    for (let idx = 0; idx < days.length; idx += 7) {
      const weekDays = days.slice(idx, idx + 7)
      let totalKm = 0
      let totalSec = 0
      let plannedKm = 0
      for (const wd of weekDays) {
        const dateStr = format(wd, 'yyyy-MM-dd')
        const acts = activityMap[dateStr] || []
        for (const a of acts) {
          totalKm += a.distance_km ?? 0
          totalSec += a.moving_time ?? 0
        }
        for (const s of sessionMap[dateStr] || []) {
          plannedKm += s.planned_distance_km ?? 0
        }
      }
      const goals = weeklyGoals.map(g => {
        let current = 0
        for (const wd of weekDays) {
          const acts = activityMap[format(wd, 'yyyy-MM-dd')] || []
          for (const a of acts) {
            if (g.sport_type !== '__all__' && a.sport_type !== g.sport_type) continue
            current += GOAL_METRIC_VALUE[g.metric](a)
          }
        }
        const target = g.target_value
        const pct = target > 0 ? (current / target) * 100 : 0
        return { ...g, current_value: current, percentage: pct }
      })
      summaries[idx] = {
        totalKm,
        timeStr: formatDurationHM(totalSec),
        plannedKm,
        hasContent: totalSec > 0 || totalKm > 0 || plannedKm > 0,
        goals,
      }
    }
    return summaries
  }, [days, activityMap, sessionMap, calGoals, showSport])

  /** The month grid as one block per week, each carrying its own totals. */
  const weekRows = useMemo(() => {
    const rows: { monday: string; days: Date[]; summary: WeekSummary | undefined }[] = []
    for (let idx = 0; idx < days.length; idx += 7) {
      const weekDays = days.slice(idx, idx + 7)
      rows.push({ monday: format(weekDays[0], 'yyyy-MM-dd'), days: weekDays, summary: weekSummaries[idx] })
    }
    return rows
  }, [days, weekSummaries])

  function handleAddSession(data: Record<string, unknown>) {
    if (!selectedDate) return
    createSession.mutate({ date: selectedDate, title: data.sport_type as string, ...data })
  }

  const handleCopySession = useCallback((session: TrainingSession, targetDate: string) => {
    const copyFields = [
      'sport_type', 'description',
      'planned_distance_km', 'planned_duration_mins', 'planned_intensity',
      'target_avg_pace', 'target_pace_min', 'target_pace_max',
      'target_hr_zone', 'target_zone_pct',
      'segments', 'workout_template_id',
    ] as const
    const data: Record<string, unknown> = { date: targetDate, title: session.sport_type }
    for (const f of copyFields) {
      if (session[f] != null) data[f] = session[f]
    }
    createSession.mutate(data)
    showToast(`Session copied to ${format(parseISO(targetDate), 'EEE, MMM d')}`)
  }, [createSession, showToast])

  function handleUpdateSession(id: number, data: Record<string, unknown>) {
    updateSession.mutate({ id, title: data.sport_type as string, ...data })
  }

  const openDay = useCallback((dateStr: string) => {
    setSelectedDate(dateStr)
    setShowModal(true)
  }, [])

  /** Drop-target props shared by the month cells and the week rows. */
  const dayDropProps = useCallback((dateStr: string, day: Date): DayDropProps => ({
    onDragOver: (e) => { e.preventDefault(); setDragOverDate(dateStr) },
    onDragLeave: () => setDragOverDate(prev => (prev === dateStr ? null : prev)),
    onDrop: (e) => {
      e.preventDefault()
      const raceId = e.dataTransfer.getData('application/race')
      const sessionId = e.dataTransfer.getData('text/plain')
      if (raceId) {
        updateRace.mutate({ id: Number(raceId), date: dateStr })
        showToast(`Race moved to ${format(day, 'EEE, MMM d')}`)
      } else if (sessionId) {
        if (e.altKey && draggingSession) {
          handleCopySession(draggingSession, dateStr)
        } else {
          updateSession.mutate({ id: Number(sessionId), date: dateStr })
          showToast(`Session moved to ${format(day, 'EEE, MMM d')}`)
        }
      }
      setDragOverDate(null)
      setDraggingSessionId(null)
      setDraggingSession(null)
    },
  }), [updateRace, updateSession, showToast, draggingSession, handleCopySession])

  const handleSessionDragStart = useCallback((e: ReactDragEvent, session: TrainingSession) => {
    e.stopPropagation()
    e.dataTransfer.setData('text/plain', String(session.id))
    e.dataTransfer.effectAllowed = 'copyMove'
    setDraggingSessionId(session.id)
    setDraggingSession(session)
  }, [])

  const handleSessionDragEnd = useCallback(() => {
    setDraggingSessionId(null)
    setDraggingSession(null)
    setDragOverDate(null)
  }, [])

  const handleRaceDragStart = useCallback((e: ReactDragEvent, race: RaceEvent) => {
    e.stopPropagation()
    e.dataTransfer.setData('application/race', String(race.id))
    e.dataTransfer.effectAllowed = 'move'
  }, [])

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      {/* ── Breadcrumb header ─────────────────────────── */}
      <header className="space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-baseline gap-2">
            <span className="eyebrow">Calendar</span>
            <span className={clsx('text-[11px]', isLight ? 'text-gray-300' : 'text-gray-700')}>·</span>
            <span className="text-[11px] text-gray-500 normal-case tracking-normal">sessions, activities, and plans</span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-0.5" role="group" aria-label="Calendar view">
              <button
                className="chip"
                data-active={view === 'month'}
                aria-pressed={view === 'month'}
                onClick={() => switchView('month')}
              >
                Month
              </button>
              <button
                className="chip"
                data-active={view === 'week'}
                aria-pressed={view === 'week'}
                onClick={() => switchView('week')}
              >
                Week
              </button>
            </div>
            <div className="flex items-center gap-1.5 relative">
              {view === 'month' ? (
                <>
                  <button onClick={() => setCurrentMonth(m => subMonths(m, 1))} className="btn !px-3" aria-label="Previous month">&larr;</button>
                  <button
                    onClick={() => setShowMonthPicker(v => !v)}
                    className="btn min-w-[150px] text-center !text-sm tabular-nums"
                  >
                    {format(currentMonth, 'MMMM yyyy')}
                  </button>
                  <button onClick={() => setCurrentMonth(m => addMonths(m, 1))} className="btn !px-3" aria-label="Next month">&rarr;</button>
                  {showMonthPicker && (
                    <MonthPicker
                      current={currentMonth}
                      onSelect={setCurrentMonth}
                      onClose={() => setShowMonthPicker(false)}
                    />
                  )}
                </>
              ) : (
                <>
                  <button
                    onClick={() => setPickedWeek(format(subDays(parseISO(weekStart), 7), 'yyyy-MM-dd'))}
                    className="btn !px-3"
                    aria-label="Previous week"
                  >&larr;</button>
                  <button
                    onClick={() => setShowWeekPicker(v => !v)}
                    className="btn min-w-[150px] text-center !text-sm tabular-nums"
                  >
                    {formatWeekRange(weekStart)}
                  </button>
                  {/* Unclamped, unlike the report's own picker in month view — the
                      point of week view is reading a plan that lives in the future. */}
                  <button
                    onClick={() => setPickedWeek(format(addDays(parseISO(weekStart), 7), 'yyyy-MM-dd'))}
                    className="btn !px-3"
                    aria-label="Next week"
                  >&rarr;</button>
                  {showWeekPicker && (
                    <WeekPicker
                      currentWeekStart={weekStart}
                      onSelect={setPickedWeek}
                      onClose={() => setShowWeekPicker(false)}
                    />
                  )}
                </>
              )}
            </div>
          </div>
        </div>
        {/* Streak + plan accomplishment badges */}
        {((streakData && (streakData.current_streak > 0 || streakData.longest_streak > 0 || (streakData.current_week_streak ?? 0) > 0 || (streakData.longest_week_streak ?? 0) > 0)) || planRate?.rate != null) && (
          <div className="flex items-center gap-1.5 flex-wrap">
            {streakData && streakData.current_streak > 0 && (
              <StreakBadge
                value={streakData.current_streak}
                label={`day${streakData.current_streak !== 1 ? 's' : ''}`}
                kind="current"
                title="Current streak — consecutive days with activities"
              />
            )}
            {streakData && streakData.longest_streak > 0 && (
              <StreakBadge
                value={streakData.longest_streak}
                label="best days"
                kind="best"
                title={`Longest day streak: ${streakData.longest_streak_start} to ${streakData.longest_streak_end}`}
              />
            )}
            {streakData && streakData.current_week_streak != null && streakData.current_week_streak > 0 && (
              <StreakBadge
                value={streakData.current_week_streak}
                label={`wk${streakData.current_week_streak !== 1 ? 's' : ''}`}
                kind="current"
                title="Current streak — consecutive weeks with activities"
              />
            )}
            {streakData && streakData.longest_week_streak != null && streakData.longest_week_streak > 0 && (
              <StreakBadge
                value={streakData.longest_week_streak}
                label="best wks"
                kind="best"
                title={`Longest week streak: ${streakData.longest_week_streak_start} to ${streakData.longest_week_streak_end}`}
              />
            )}
            {/* All-time plan rate splits into a recent badge only once history outgrows the window */}
            {planRate?.rate != null && (
              <>
                {planRate.recent_rate != null && planRate.recent_planned < planRate.total_planned && (
                  <PlanRateBadge
                    rate={planRate.recent_rate}
                    label="plan 4wk"
                    title={`Plan accomplishment, last ${planRate.window_days} days: ${planRate.recent_completed} of ${planRate.recent_planned} planned sessions completed`}
                  />
                )}
                <PlanRateBadge
                  rate={planRate.rate}
                  label={planRate.recent_planned < planRate.total_planned ? 'plan all' : 'plan'}
                  title={`Plan accomplishment, all time: ${planRate.total_completed} of ${planRate.total_planned} planned sessions completed`}
                />
              </>
            )}
          </div>
        )}

        {/* Race countdown banner */}
        {upcomingRaces && upcomingRaces.length > 0 && (() => {
          const nextRace = upcomingRaces[0]
          const daysUntil = differenceInCalendarDays(parseLocalDate(nextRace.date), new Date())
          return (
            <Link
              to="/races"
              className={clsx(
                'panel flex items-center gap-4 px-4 py-3 transition-colors group',
                isLight ? 'bg-amber-50 border-amber-200 hover:border-amber-300' : 'bg-amber-500/5 border-amber-500/20 hover:border-amber-500/40',
              )}
              style={{ ['--card-accent' as string]: '#eab308' }}
            >
              <div
                className="flex flex-col items-center justify-center rounded-lg px-3 py-1.5 shrink-0 min-w-[58px] border"
                style={{ backgroundColor: '#eab30810', borderColor: '#eab30830' }}
              >
                {daysUntil === 0 ? (
                  <div className="text-sm font-mono font-bold leading-none py-1.5" style={{ color: '#eab308' }}>
                    Today
                  </div>
                ) : (
                  <>
                    <div
                      className="text-xl font-mono tabular-nums font-bold leading-none"
                      style={{ color: '#eab308', letterSpacing: '-0.02em' }}
                    >
                      {daysUntil}
                    </div>
                    <div className="eyebrow mt-0.5 text-[9px]" style={{ color: '#eab308cc' }}>
                      day{daysUntil !== 1 ? 's' : ''}
                    </div>
                  </>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span style={{ color: '#eab308' }}><FlagIcon size={11} /></span>
                  <span className={clsx('text-sm font-semibold tracking-tight truncate', isLight ? 'text-gray-900' : 'text-gray-100')}>
                    {nextRace.name}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-[11px] text-gray-500 flex-wrap font-mono tabular-nums">
                  <span>{nextRace.sport_type}</span>
                  {nextRace.distance_km != null && <span>{formatDistExact(nextRace.distance_km, nextRace.sport_type)}</span>}
                  {nextRace.location && <span className="normal-case">{nextRace.location}</span>}
                  <span>{format(parseISO(nextRace.date), 'MMM d, yyyy')}</span>
                </div>
              </div>
              {upcomingRaces.length > 1 && (
                <div className="hidden md:flex items-center gap-1 shrink-0">
                  {upcomingRaces.slice(1, 4).map(r => {
                    const d = differenceInCalendarDays(parseLocalDate(r.date), new Date())
                    return (
                      <div
                        key={r.id}
                        className={clsx(
                          'flex items-center gap-1 border rounded-lg px-2 py-0.5',
                          isLight ? 'bg-white border-amber-200' : 'bg-surface-800 border-amber-500/20',
                        )}
                        title={`${r.name}: ${format(parseISO(r.date), 'MMM d, yyyy')}`}
                      >
                        <span className="text-[11px] font-mono tabular-nums font-semibold text-amber-500">{d === 0 ? 'Today' : `${d}d`}</span>
                        <span className="text-[10px] text-gray-500 truncate max-w-[72px]">{r.name}</span>
                      </div>
                    )
                  })}
                </div>
              )}
            </Link>
          )
        })()}
      </header>

      {/* Sport filter — scopes what the grid shows and what its week totals count.
          The weekly report below is computed server-side and stays all-sport. */}
      {sportChips.length > 1 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="eyebrow mr-0.5">Sports</span>
          <button
            className="chip"
            data-active={sportFilter.size === 0}
            aria-pressed={sportFilter.size === 0}
            onClick={() => setSportFilter(new Set())}
          >
            All
          </button>
          {sportChips.map(sport => (
            <button
              key={sport}
              className="chip inline-flex items-center gap-1.5"
              data-active={sportFilter.has(sport)}
              aria-pressed={sportFilter.has(sport)}
              onClick={() => toggleSport(sport)}
            >
              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: getSportColor(sport) }} />
              {sport}
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px] gap-4 items-start">
        <div className="min-w-0">
          {view === 'week' ? (
            <WeekView
              days={days}
              summary={weekSummaries[0]}
              activityMap={activityMap}
              sessionMap={sessionMap}
              raceMap={raceMap}
              scores={sessionScores}
              dragOverDate={dragOverDate}
              draggingSessionId={draggingSessionId}
              dayDropProps={dayDropProps}
              onOpenDay={openDay}
              onSessionDragStart={handleSessionDragStart}
              onSessionDragEnd={handleSessionDragEnd}
              onRaceDragStart={handleRaceDragStart}
            />
          ) : (
            /* Month grid — one block per week, so a week's totals sit under its own
               days and the whole row is a single selection target for the inspector.
               All seven columns fit at every width; below md the cells shrink to dots
               and the day modal carries the detail. */
            <div key={format(currentMonth, 'yyyy-MM')} style={{ animation: 'fadeIn 200ms ease-out' }}>
              <div className="grid grid-cols-7 gap-0.5 md:gap-1 px-1">
                {WEEKDAYS_SHORT.map((d, i) => (
                  <div key={d} className="eyebrow text-center py-1.5 !text-[9px] md:!text-[11px] !tracking-[0.08em] md:!tracking-[0.18em]">
                    <span className="md:hidden">{WEEKDAYS_MIN[i]}</span>
                    <span className="hidden md:inline">{d}</span>
                  </div>
                ))}
              </div>

              {activitiesLoading ? (
                <div className="space-y-1">
                  {Array.from({ length: 5 }).map((_, r) => (
                    <div key={r} className="grid grid-cols-7 gap-0.5 md:gap-1 p-1">
                      {Array.from({ length: 7 }).map((_, c) => (
                        <div
                          key={c}
                          className={clsx(
                            'min-h-[54px] md:min-h-[120px] rounded-lg border animate-pulse',
                            isLight ? 'bg-gray-100 border-gray-200' : 'bg-surface-800 border-surface-600',
                          )}
                        />
                      ))}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-1">
                  {weekRows.map(row => {
                    const selected = row.monday === weekStart
                    return (
                      <div
                        key={row.monday}
                        onClick={() => setPickedWeek(row.monday)}
                        aria-current={selected ? 'true' : undefined}
                        className={clsx(
                          'rounded-xl p-1 border transition-colors cursor-pointer',
                          selected
                            ? (isLight ? 'bg-blue-50/70 border-blue-200' : 'bg-blue-400/[0.05] border-blue-400/25')
                            : (isLight ? 'border-transparent hover:border-gray-200' : 'border-transparent hover:border-surface-600'),
                        )}
                      >
                        <div className="grid grid-cols-7 gap-0.5 md:gap-1">
                          {row.days.map(day => {
                            const dateStr = format(day, 'yyyy-MM-dd')
                            const dayActivities = activityMap[dateStr] || []
                            const daySessions = sessionMap[dateStr] || []
                            const inMonth = isSameMonth(day, currentMonth)
                            const isPastOrToday = day <= new Date(new Date().setHours(23, 59, 59, 999))
                            const planStatus = dayPlanStatus(daySessions, dayActivities, isPastOrToday)
                            return (
                              <div
                                key={dateStr}
                                onClick={() => openDay(dateStr)}
                                {...dayDropProps(dateStr, day)}
                                className={clsx(
                                  'relative min-h-[54px] md:min-h-[120px] p-1 md:p-2 rounded-lg border transition-all duration-150',
                                  'cursor-pointer',
                                  inMonth
                                    ? isLight ? 'border-gray-200 bg-white' : 'border-surface-600 bg-surface-800'
                                    : isLight ? 'border-transparent bg-gray-50/50' : 'border-transparent bg-surface-900/50',
                                  isToday(day) && (isLight ? 'ring-1 ring-gray-400/40 border-gray-300' : 'ring-1 ring-gray-500/30 border-gray-500/40'),
                                  dragOverDate === dateStr ? 'border-gray-400/60 ring-2 ring-gray-400/20 bg-gray-400/[0.03]' : 'hover:border-surface-500',
                                )}
                              >
                                <div className="flex items-center justify-between mb-1">
                                  <span className={clsx(
                                    'text-xs font-medium',
                                    isToday(day) ? (isLight ? 'bg-gray-900 text-white w-5 h-5 rounded-full flex items-center justify-center text-[10px]' : 'bg-gray-400/20 text-gray-100 w-5 h-5 rounded-full flex items-center justify-center text-[10px]')
                                      : inMonth ? (isLight ? 'text-gray-600' : 'text-gray-400')
                                      : 'text-gray-600',
                                  )}>
                                    {format(day, 'd')}
                                  </span>
                                </div>
                                {planStatus && (() => {
                                  const avgScore = dayAvgScore(daySessions, sessionScores)
                                  return (
                                    <div className="absolute top-1 right-1 flex items-center gap-1">
                                      {avgScore !== null && (
                                        <span
                                          className="hidden md:inline text-[9px] font-bold font-mono px-1 rounded"
                                          style={{ color: scoreColor(avgScore), backgroundColor: `${scoreColor(avgScore)}15` }}
                                        >
                                          {avgScore}
                                        </span>
                                      )}
                                      <span
                                        className={clsx('w-2 h-2 rounded-full', planStatus === 'done' ? 'bg-green-400' : 'bg-red-400')}
                                        title={planStatus === 'done' ? 'Plan completed' : 'Plan missed'}
                                      />
                                    </div>
                                  )
                                })()}
                                {/* Mobile: dots stand in for the labelled rows — filled for logged
                                    activities, outlined for planned sessions. Nothing legible fits a
                                    ~45px cell, and the whole cell taps through to the day modal. */}
                                <div className="md:hidden flex flex-wrap items-center gap-[3px]">
                                  {dayActivities.slice(0, MOBILE_DOT_LIMIT).map(a => (
                                    <span
                                      key={a.id}
                                      className="w-1.5 h-1.5 rounded-full"
                                      style={{ backgroundColor: getSportColor(a.sport_type) }}
                                    />
                                  ))}
                                  {daySessions.slice(0, Math.max(0, MOBILE_DOT_LIMIT - dayActivities.length)).map(s => (
                                    <span
                                      key={s.id as number}
                                      className="w-1.5 h-1.5 rounded-full border"
                                      style={{ borderColor: getSportColor(s.sport_type as string) }}
                                    />
                                  ))}
                                  {dayActivities.length + daySessions.length > MOBILE_DOT_LIMIT && (
                                    <span className="text-[8px] font-mono leading-none text-gray-500">
                                      +{dayActivities.length + daySessions.length - MOBILE_DOT_LIMIT}
                                    </span>
                                  )}
                                  {(raceMap[dateStr] || []).length > 0 && (
                                    <span className="text-amber-500 leading-none"><FlagIcon size={8} /></span>
                                  )}
                                </div>

                                <div className="hidden md:block">
                                  <div className="space-y-0.5">
                                    {dayActivities.map((a) => (
                                      <Link key={a.id} to={`/activities/${a.id}`} onClick={e => e.stopPropagation()} className={clsx('flex items-center gap-1.5 group rounded px-1 py-0.5 -mx-1 transition-colors', isLight ? 'hover:bg-black/[0.04]' : 'hover:bg-white/[0.04]')}>
                                        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: getSportColor(a.sport_type) }} />
                                        <span className={clsx('text-[10px] truncate leading-tight', isLight ? 'text-gray-500 group-hover:text-gray-900' : 'text-gray-400 group-hover:text-gray-100')}>{a.name}</span>
                                      </Link>
                                    ))}
                                  </div>
                                  {daySessions.map((s) => {
                                    const sColor = getSportColor(s.sport_type as string)
                                    return (
                                      <div
                                        key={s.id as number}
                                        draggable
                                        onDragStart={(e) => handleSessionDragStart(e, s)}
                                        onDragEnd={handleSessionDragEnd}
                                        className={clsx(
                                          'mt-0.5 text-[10px] px-1.5 py-0.5 rounded border border-dashed truncate cursor-grab active:cursor-grabbing',
                                          'transition-all duration-150 hover:scale-[1.02]',
                                          draggingSessionId === (s.id as number) && 'opacity-40 scale-95 rotate-1',
                                        )}
                                        style={{
                                          borderColor: `${sColor}60`,
                                          color: `${sColor}bb`,
                                        }}
                                        onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.boxShadow = `0 0 8px ${sColor}30` }}
                                        onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.boxShadow = 'none' }}
                                        title={s.description as string || s.sport_type as string}
                                      >
                                        {s.description ? `${s.sport_type}: ${s.description}` : s.sport_type as string}
                                      </div>
                                    )
                                  })}
                                  {(raceMap[dateStr] || []).map((r) => {
                                    const matchedActivity = isPastOrToday
                                      ? dayActivities.find(a => a.sport_type === r.sport_type)
                                      : null
                                    return (
                                      <div
                                        key={`race-${r.id}`}
                                        draggable
                                        onDragStart={(e) => handleRaceDragStart(e, r)}
                                        className={clsx(
                                          'mt-0.5 text-[10px] px-1.5 py-0.5 rounded border truncate',
                                          'cursor-grab active:cursor-grabbing transition-all duration-150 hover:scale-[1.02]',
                                          'border-amber-500/60 text-amber-500/90 bg-amber-500/5',
                                        )}
                                        title={`${r.name}${r.location ? ` — ${r.location}` : ''}${r.distance_km != null ? ` (${formatDistExact(r.distance_km, r.sport_type)})` : ''}`}
                                      >
                                        <span className="inline-flex items-center gap-1"><FlagIcon size={9} /> {r.name as string}</span>
                                        {matchedActivity && (
                                          <Link to={`/activities/${matchedActivity.id}`} onClick={e => e.stopPropagation()} className="text-green-400 ml-1 inline-flex items-center align-middle">
                                            <CheckIcon size={9} />
                                          </Link>
                                        )}
                                      </div>
                                    )
                                  })}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                        {row.summary?.hasContent && (
                          <WeekTotals
                            summary={row.summary}
                            className="justify-start md:justify-end px-1 md:px-2 pt-1.5"
                          />
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        <WeekInspector
          weekStart={weekStart}
          report={current}
          loading={weekLoading}
          activities={weekActivities?.items}
          goals={goalProgressData?.goals}
          planned={weekPlanned}
          todayStr={todayStr}
          atCurrentWeek={isCurrentWeek}
          delta={delta}
          onPrev={() => setPickedWeek(format(subDays(parseISO(weekStart), 7), 'yyyy-MM-dd'))}
          onNext={() => setPickedWeek(() => {
            const next = format(addDays(parseISO(weekStart), 7), 'yyyy-MM-dd')
            return next > thisWeekStart ? thisWeekStart : next
          })}
          onPickDay={openDay}
        />
      </div>

      {/* Weekly Report — fade in */}
      <style>{`
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes scaleIn { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }
      `}</style>
      <section>
        <div className="flex items-baseline gap-2.5 mb-4 flex-wrap">
          <span className="eyebrow shrink-0">Week detail</span>
          <span className={clsx('text-[11px]', isLight ? 'text-gray-300' : 'text-gray-700')}>·</span>
          <span className="text-xs font-semibold text-blue-400 shrink-0">{formatWeekRange(weekStart)}</span>
          <span className="text-[11px] text-gray-500 shrink-0">follows the week selected above</span>
          <div className="section-head flex-1 min-w-[40px]" />
        </div>

        {weekLoading ? weekDetailSkeleton : current ? (
          <Suspense fallback={weekDetailSkeleton}>
            <WeekDetailCharts current={current} previous={previous} colorMap={weekSportColors} hrZoneBounds={hrZoneBounds} />
          </Suspense>
        ) : null}
      </section>

      {/* Session Modal */}
      {showModal && selectedDate && (
        <Suspense fallback={null}>
        <SessionModal
          date={selectedDate}
          sessions={sessionMap[selectedDate] || []}
          scores={sessionScores}
          races={raceMap[selectedDate] || []}
          onAdd={handleAddSession}
          onCopy={handleCopySession}
          onUpdate={handleUpdateSession}
          onDelete={(id: number) => deleteSession.mutate(id)}
          onAddRace={(data) => createRace.mutate({ date: selectedDate, ...data })}
          onUpdateRace={(id, data) => updateRace.mutate({ id, ...data })}
          onDeleteRace={(id) => deleteRace.mutate(id)}
          onClose={() => setShowModal(false)}
        />
        </Suspense>
      )}

    </div>
  )
}
