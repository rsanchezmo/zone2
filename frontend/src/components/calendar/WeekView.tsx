import { format, isToday } from 'date-fns'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { getSportColor } from '../../constants/sportColors'
import { useTheme } from '../../hooks/useTheme'
import { formatDist, formatDurationHM, formatDistExact } from '../../utils/formatSpeed'
import { scoreColor } from '../../utils/scoreColor'
import { SegmentSummary, type Segment } from '../shared/SegmentListBuilder'
import { FlagIcon } from '../icons'
import {
  dayAvgScore, dayPlanStatus, sessionGoalChips, type CalendarGridProps, type WeekSummary,
} from './calendar'
import GoalChips from './GoalChips'
import WeekTotals from './WeekTotals'
import WatchStatus from './WatchStatus'

interface WeekViewProps extends CalendarGridProps {
  days: Date[]
  summary: WeekSummary | undefined
}

/** One full-width row per day. Sessions are day-scoped, so a time grid would
 *  imply an ordering the data doesn't carry — the rows stay a plain list. */
export default function WeekView({
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
              <div className="eyebrow text-[9px]">{format(day, 'EEE')}</div>
              <div
                className={clsx(
                  'font-mono tabular-nums text-lg leading-none mt-0.5',
                  today ? (isLight ? 'text-gray-900 font-semibold' : 'text-gray-100 font-semibold') : 'text-gray-400',
                )}
                style={{ letterSpacing: '-0.02em' }}
              >
                {format(day, 'd')}
              </div>
              {today && <div className="eyebrow text-[8px] mt-1">today</div>}
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
                      <WatchStatus session={s} />
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
