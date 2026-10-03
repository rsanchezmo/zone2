import { format, isSameMonth, isToday } from 'date-fns'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { getSportColor } from '../../constants/sportColors'
import { WEEKDAYS_SHORT, WEEKDAYS_MIN } from '../../constants/weekdays'
import { useTheme } from '../../hooks/useTheme'
import { formatDistExact } from '../../utils/formatSpeed'
import { scoreColor } from '../../utils/scoreColor'
import { FlagIcon, CheckIcon } from '../icons'
import { dayAvgScore, dayPlanStatus, type CalendarGridProps, type WeekRow } from './calendar'
import WeekTotals from './WeekTotals'
import WatchStatus from './WatchStatus'

/** Dots that fit across a day cell on the compact mobile grid before overflowing to a "+n". */
const MOBILE_DOT_LIMIT = 4

interface MonthGridProps extends CalendarGridProps {
  currentMonth: Date
  weekRows: WeekRow[]
  /** Monday of the week the inspector shows. */
  selectedWeek: string
  loading: boolean
  onPickWeek: (monday: string) => void
}

/** One block per week, so a week's totals sit under its own days and the whole
 *  row is a single selection target for the inspector. All seven columns fit at
 *  every width; below md the cells shrink to dots and the day modal carries the detail. */
export default function MonthGrid({
  currentMonth, weekRows, selectedWeek, loading, activityMap, sessionMap, raceMap, scores,
  dragOverDate, draggingSessionId, dayDropProps, onPickWeek, onOpenDay, onSessionDragStart,
  onSessionDragEnd, onRaceDragStart,
}: MonthGridProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'

  return (
    <div style={{ animation: 'fadeIn 200ms ease-out' }}>
      <div className="grid grid-cols-7 gap-0.5 md:gap-1 px-1">
        {WEEKDAYS_SHORT.map((d, i) => (
          <div key={d} className="eyebrow text-center py-1.5 !text-[9px] md:!text-[11px] !tracking-[0.08em] md:!tracking-[0.18em]">
            <span className="md:hidden">{WEEKDAYS_MIN[i]}</span>
            <span className="hidden md:inline">{d}</span>
          </div>
        ))}
      </div>

      {loading ? (
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
            const selected = row.monday === selectedWeek
            return (
              <div
                key={row.monday}
                onClick={() => onPickWeek(row.monday)}
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
                        onClick={() => onOpenDay(dateStr)}
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
                          const avgScore = dayAvgScore(daySessions, scores)
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
                                onDragStart={(e) => onSessionDragStart(e, s)}
                                onDragEnd={onSessionDragEnd}
                                className={clsx(
                                  'mt-0.5 text-[10px] px-1.5 py-0.5 rounded border border-dashed flex items-center gap-1 cursor-grab active:cursor-grabbing',
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
                                <span className="truncate">{s.description ? `${s.sport_type}: ${s.description}` : s.sport_type}</span>
                                <WatchStatus session={s} size={9} />
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
                                onDragStart={(e) => onRaceDragStart(e, r)}
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
  )
}
