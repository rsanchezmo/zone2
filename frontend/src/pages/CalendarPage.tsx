import { useState, useMemo } from 'react'
import {
  startOfMonth, endOfMonth, eachDayOfInterval, format, addMonths, subMonths, addDays, subDays,
  isSameMonth, isToday, startOfWeek, endOfWeek,
} from 'date-fns'
import { Link } from 'react-router-dom'
import {
  useActivitiesByDateRange, useCalendarSessions, useCalendarSessionsByRange,
  useCreateSession, useUpdateSession, useDeleteSession, useWeeklyReport,
} from '../api/hooks'
import { SPORT_COLORS_HEX, getSportColor } from '../constants/sportColors'
import StatCard from '../components/shared/StatCard'
import ExportButton from '../components/shared/ExportButton'
import clsx from 'clsx'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  PieChart, Pie, Cell,
} from 'recharts'
import { useTheme } from '../hooks/useTheme'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/* ── Sport Pie Chart ────────────────────────────────── */
function SportPieChart({ title, data, formatValue, colorMap }: {
  title: string
  data: Record<string, number>
  formatValue: (v: number) => string
  colorMap: Record<string, string>
}) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const pieData = useMemo(() => {
    return Object.entries(data)
      .filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([name, value]) => ({
        name,
        value: Math.round(value * 10) / 10,
        color: colorMap[name] ?? '#9ca3af',
      }))
  }, [data, colorMap])

  if (pieData.length === 0) return null

  const renderLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, value }: any) => {
    const RADIAN = Math.PI / 180
    const radius = innerRadius + (outerRadius - innerRadius) * 0.4
    const x = cx + radius * Math.cos(-midAngle * RADIAN)
    const y = cy + radius * Math.sin(-midAngle * RADIAN)
    return (
      <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={10} fontFamily="monospace" fontWeight="bold">
        {Math.round(value * 10) / 10}
      </text>
    )
  }

  return (
    <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
      <div className="text-xs text-gray-500 uppercase mb-2">{title}</div>
      <div className="flex gap-3 mb-2 flex-wrap">
        {pieData.map(d => (
          <div key={d.name} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.color }} />
            <span className="text-[11px] text-gray-400">{d.name}</span>
          </div>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie
            data={pieData}
            dataKey="value"
            cx="50%"
            cy="50%"
            innerRadius={15}
            outerRadius={75}
            strokeWidth={2}
            stroke="none"
            label={renderLabel}
            labelLine={false}
          >
            {pieData.map((d, i) => (
              <Cell key={i} fill={d.color} fillOpacity={0.3} stroke={d.color} strokeWidth={2} strokeOpacity={1} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
            formatter={(value: number, name: string) => [formatValue(value), name]}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ── Accumulated Chart ──────────────────────────────── */
interface AccumulatedChartProps {
  data: Record<string, Record<string, number>>
  titles?: Record<string, Record<string, string[]>>
  colorMap: Record<string, string>
}

function AccumulatedChart({ data, titles, colorMap }: AccumulatedChartProps) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const { chartData, sports, sportColorMap, activeDays } = useMemo(() => {
    const sportTotals = Object.entries(data).map(([sport, days]) => ({
      sport,
      total: Object.values(days).reduce((a, b) => a + b, 0),
    }))
    sportTotals.sort((a, b) => b.total - a.total)
    const sports = sportTotals.map(s => s.sport)
    const sportColorMap: Record<string, string> = {}
    sports.forEach((s) => { sportColorMap[s] = colorMap[s] ?? getSportColor(s) })

    const activeDays: Record<string, Set<number>> = {}
    for (const sport of sports) {
      activeDays[sport] = new Set()
      for (let d = 0; d < 7; d++) {
        if ((data[sport]?.[d] ?? 0) > 0) activeDays[sport].add(d)
      }
    }

    const chartData = WEEKDAYS.map((day, dayIdx) => {
      const point: Record<string, unknown> = { day, _dayIdx: dayIdx }
      for (const sport of sports) {
        let accum = 0
        for (let d = 0; d <= dayIdx; d++) {
          accum += data[sport]?.[d] ?? 0
        }
        point[sport] = Math.round(accum)
      }
      return point
    })

    return { chartData, sports, sportColorMap, activeDays }
  }, [data])

  if (sports.length === 0) return null

  function makeActiveDot(sport: string, color: string) {
    return (props: Record<string, unknown>) => {
      const { cx, cy, index } = props as { cx: number; cy: number; index: number }
      if (!activeDays[sport]?.has(index)) return <g />
      return <circle cx={cx} cy={cy} r={4} fill={color} stroke={isLight ? '#1f2937' : '#fff'} strokeWidth={1.5} />
    }
  }

  function makeLabel(sport: string, color: string) {
    return (props: Record<string, unknown>) => {
      const { x, y, index } = props as { x: number; y: number; index: number }
      if (!activeDays[sport]?.has(index)) return <g />
      const dayTitles = titles?.[sport]?.[index] ?? []
      if (dayTitles.length === 0) return <g />
      const label = dayTitles.map(t => t.length > 16 ? t.slice(0, 16) + '…' : t).join(', ')
      return (
        <text x={x} y={y - 10} textAnchor="middle" fill={color} fontSize={9} fontFamily="monospace" opacity={0.85}>
          {label}
        </text>
      )
    }
  }

  return (
    <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
      <div className="text-xs text-gray-500 uppercase mb-1">Accumulated Training Time</div>
      <div className="flex gap-3 mb-3 flex-wrap">
        {sports.map(s => (
          <div key={s} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: sportColorMap[s] }} />
            <span className="text-[11px] text-gray-400">{s}</span>
          </div>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={chartData} margin={{ top: 20, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
          <XAxis dataKey="day" tick={{ fill: colors.tickFill, fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: colors.tickFillSecondary, fontSize: 10 }} axisLine={false} tickLine={false} width={35} tickFormatter={(v: number) => `${v}m`} />
          <Tooltip
            contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: colors.labelColor }}
            formatter={(value: number, name: string) => [`${value} min`, name]}
          />
          {sports.map(sport => (
            <Area
              key={sport}
              type="monotone"
              dataKey={sport}
              stroke={sportColorMap[sport]}
              fill={sportColorMap[sport]}
              fillOpacity={0.15}
              strokeWidth={2}
              dot={makeActiveDot(sport, sportColorMap[sport]) as any}
              label={makeLabel(sport, sportColorMap[sport]) as any}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ── Session Modal ──────────────────────────────────── */
function SessionModal({
  date, sessions, onAdd, onUpdate, onDelete, onClose,
}: {
  date: string
  sessions: Record<string, unknown>[]
  onAdd: (data: { sport_type: string; description?: string }) => void
  onUpdate: (id: number, data: { sport_type: string; description?: string }) => void
  onDelete: (id: number) => void
  onClose: () => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [sportType, setSportType] = useState('Run')
  const [description, setDescription] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)

  function startEdit(s: Record<string, unknown>) {
    setEditingId(s.id as number)
    setSportType(s.sport_type as string)
    setDescription((s.description as string) || '')
  }

  function cancelEdit() {
    setEditingId(null)
    setSportType('Run')
    setDescription('')
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-surface-800 border border-surface-600 rounded-xl p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold mb-4">{date}</h3>

        {sessions.length > 0 && (
          <div className="mb-4 space-y-2">
            <div className="text-xs text-gray-500 uppercase">Planned Sessions</div>
            {sessions.map(s => {
              const sColor = getSportColor(s.sport_type as string)
              return (
                <div key={s.id as number} className="rounded p-2 border border-dashed"
                  style={{ borderColor: `${sColor}60`, backgroundColor: `${sColor}10` }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0 cursor-pointer" onClick={() => startEdit(s)}>
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: sColor }} />
                      <span className="text-sm" style={{ color: sColor }}>{s.sport_type as string}</span>
                      {s.description && (
                        <span className="text-xs text-gray-400 truncate">{s.description as string}</span>
                      )}
                    </div>
                    <div className="flex gap-2 shrink-0 ml-2">
                      <button onClick={() => startEdit(s)} className={clsx('text-gray-400 text-xs', isLight ? 'hover:text-gray-700' : 'hover:text-gray-200')}>Edit</button>
                      <button onClick={() => onDelete(s.id as number)} className="text-red-400 hover:text-red-300 text-xs">Delete</button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        <div className="space-y-3">
          <div className="text-xs text-gray-500 uppercase">
            {editingId ? 'Edit Session' : 'Add Session'}
          </div>
          <select
            value={sportType}
            onChange={e => setSportType(e.target.value)}
            className="w-full bg-surface-700 border border-surface-600 rounded px-3 py-2 text-sm"
          >
            {Object.keys(SPORT_COLORS_HEX).map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
            <option value="Other">Other</option>
          </select>
          <textarea
            placeholder="Description (optional)"
            value={description}
            onChange={e => setDescription(e.target.value)}
            className="w-full bg-surface-700 border border-surface-600 rounded px-3 py-2 text-sm"
            rows={2}
          />
          <div className="flex gap-2 pt-2">
            <button
              onClick={() => {
                if (editingId) {
                  onUpdate(editingId, { sport_type: sportType, description: description || undefined })
                  cancelEdit()
                } else {
                  onAdd({ sport_type: sportType, description: description || undefined })
                  setDescription('')
                }
              }}
              className="flex-1 bg-neon-red/20 text-neon-red border border-neon-red/30 rounded py-2 text-sm hover:bg-neon-red/30 transition-colors"
            >
              {editingId ? 'Save' : 'Add'}
            </button>
            {editingId ? (
              <button onClick={cancelEdit} className={clsx('flex-1 bg-surface-700 rounded py-2 text-sm text-gray-400', isLight ? 'hover:text-gray-700' : 'hover:text-gray-200')}>
                Cancel Edit
              </button>
            ) : (
              <button onClick={onClose} className={clsx('flex-1 bg-surface-700 rounded py-2 text-sm text-gray-400', isLight ? 'hover:text-gray-700' : 'hover:text-gray-200')}>
                Cancel
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Upcoming Plan (expandable) ─────────────────────── */
function UpcomingPlan({ sessions, todayStr }: { sessions: Record<string, unknown>[] | undefined; todayStr: string }) {
  const [expandedId, setExpandedId] = useState<number | null>(null)

  return (
    <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
      <div className="text-xs text-gray-500 uppercase mb-3">Upcoming Plan (7 days)</div>
      {sessions && sessions.length > 0 ? (
        <div className="space-y-2">
          {sessions.map((s: Record<string, unknown>) => {
            const color = getSportColor(s.sport_type as string)
            const sessionDate = new Date(s.date as string + 'T00:00:00')
            const isTodaySession = s.date === todayStr
            const isExpanded = expandedId === (s.id as number)
            return (
              <div
                key={s.id as number}
                className="rounded-lg border border-dashed transition-colors cursor-pointer"
                style={{ borderColor: `${color}40` }}
                onClick={() => setExpandedId(isExpanded ? null : s.id as number)}
              >
                <div className="flex items-center gap-3 px-3 py-2">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
                  <span className="text-sm font-medium shrink-0" style={{ color }}>{s.sport_type as string}</span>
                  {!isExpanded && s.description && (
                    <span className="text-sm text-gray-400 truncate flex-1">{s.description as string}</span>
                  )}
                  {(!s.description || isExpanded) && <span className="flex-1" />}
                  <span className="text-xs text-gray-500 shrink-0">
                    {isTodaySession ? 'Today' : format(sessionDate, 'EEE, MMM d')}
                  </span>
                  <span className="text-[10px] text-gray-600 shrink-0">{isExpanded ? '▲' : '▼'}</span>
                </div>
                {isExpanded && (
                  <div className="px-3 pb-3 pt-1 border-t border-dashed" style={{ borderColor: `${color}20` }}>
                    <p className="text-sm text-gray-300 whitespace-pre-wrap">
                      {(s.description as string) || 'No description'}
                    </p>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <div className="text-sm text-gray-600">No upcoming sessions</div>
      )}
    </div>
  )
}

/* ── Calendar Page ──────────────────────────────────── */
export default function CalendarPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [currentMonth, setCurrentMonth] = useState(new Date())
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)

  const month = currentMonth.getMonth() + 1
  const year = currentMonth.getFullYear()

  const monthStart = startOfMonth(currentMonth)
  const monthEnd = endOfMonth(currentMonth)
  const calStart = startOfWeek(monthStart, { weekStartsOn: 1 })
  const calEnd = endOfWeek(monthEnd, { weekStartsOn: 1 })
  const days = eachDayOfInterval({ start: calStart, end: calEnd })

  const dateFrom = format(calStart, 'yyyy-MM-dd')
  const dateTo = format(calEnd, 'yyyy-MM-dd')

  const { data: activitiesData } = useActivitiesByDateRange(dateFrom, dateTo)
  const { data: sessions } = useCalendarSessions(month, year)
  const createSession = useCreateSession()
  const updateSession = useUpdateSession()
  const deleteSession = useDeleteSession()

  // Weekly report
  const [weekOffset, setWeekOffset] = useState(0)
  const weekStart = format(
    subDays(startOfWeek(new Date(), { weekStartsOn: 1 }), weekOffset * 7),
    'yyyy-MM-dd'
  )
  const { data: weekData, isLoading: weekLoading } = useWeeklyReport(weekStart)
  const current = weekData?.current
  const previous = weekData?.previous

  const { data: weekActivities } = useActivitiesByDateRange(current?.week_start, current?.week_end)

  // Upcoming planned sessions (next 7 days)
  const todayStr = format(new Date(), 'yyyy-MM-dd')
  const next7 = format(addDays(new Date(), 7), 'yyyy-MM-dd')
  const { data: upcomingSessions } = useCalendarSessionsByRange(todayStr, next7)

  // Shared sport color map for weekly section
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
    const c = current[key]
    const p = previous[key]
    if (c == null) return null
    if (!p || p === 0) return c > 0 ? 'new' : null
    return ((c - p) / p) * 100
  }

  // Build maps
  const activityMap = useMemo(() => {
    const map: Record<string, Array<{ id: number; name: string; sport_type: string; distance_km: number }>> = {}
    if (activitiesData?.items) {
      for (const a of activitiesData.items) {
        const dateStr = a.start_date_local ? format(new Date(a.start_date_local), 'yyyy-MM-dd') : null
        if (dateStr) {
          if (!map[dateStr]) map[dateStr] = []
          map[dateStr].push(a)
        }
      }
    }
    return map
  }, [activitiesData])

  const sessionMap = useMemo(() => {
    const map: Record<string, Array<Record<string, unknown>>> = {}
    if (sessions) {
      for (const s of sessions) {
        if (!map[s.date]) map[s.date] = []
        map[s.date].push(s)
      }
    }
    return map
  }, [sessions])

  function handleAddSession(data: { sport_type: string; description?: string }) {
    if (!selectedDate) return
    createSession.mutate({ date: selectedDate, title: data.sport_type, ...data })
  }

  function handleUpdateSession(id: number, data: { sport_type: string; description?: string }) {
    updateSession.mutate({ id, title: data.sport_type, ...data })
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Calendar header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Calendar</h2>
        <div className="flex items-center gap-3">
          <button onClick={() => setCurrentMonth(m => subMonths(m, 1))} className="bg-surface-700 hover:bg-surface-600 px-3 py-1 rounded text-sm">&larr;</button>
          <span className="text-gray-300 min-w-[120px] text-center">{format(currentMonth, 'MMMM yyyy')}</span>
          <button onClick={() => setCurrentMonth(m => addMonths(m, 1))} className="bg-surface-700 hover:bg-surface-600 px-3 py-1 rounded text-sm">&rarr;</button>
        </div>
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-1">
        {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(d => (
          <div key={d} className="text-center text-xs text-gray-500 py-1">{d}</div>
        ))}

        {days.map(day => {
          const dateStr = format(day, 'yyyy-MM-dd')
          const dayActivities = activityMap[dateStr] || []
          const daySessions = sessionMap[dateStr] || []
          const inMonth = isSameMonth(day, currentMonth)
          const isPast = day < new Date(new Date().setHours(0, 0, 0, 0))

          let planStatus: 'done' | 'missed' | null = null
          if (daySessions.length > 0 && isPast) {
            const activitySports = new Set(dayActivities.map(a => a.sport_type))
            const allMatched = daySessions.every(s => {
              const sport = (s.sport_type as string).toLowerCase()
              if (sport === 'rest') return dayActivities.length === 0
              return activitySports.has(s.sport_type as string)
            })
            planStatus = allMatched ? 'done' : 'missed'
          }

          return (
            <div
              key={dateStr}
              onClick={() => { setSelectedDate(dateStr); setShowModal(true) }}
              className={clsx(
                'relative min-h-[120px] p-2 rounded-lg border transition-colors',
                'cursor-pointer',
                inMonth ? 'border-surface-600 bg-surface-800' : 'border-transparent bg-surface-900/50',
                isToday(day) && 'border-neon-red/40',
                'hover:border-neon-red/30'
              )}
            >
              <div className={clsx('text-xs mb-1', inMonth ? 'text-gray-400' : 'text-gray-600')}>
                {format(day, 'd')}
              </div>
              {planStatus && (
                <span
                  className={clsx('absolute top-1.5 right-1.5 w-2 h-2 rounded-full', planStatus === 'done' ? 'bg-green-400' : 'bg-red-400')}
                  title={planStatus === 'done' ? 'Plan completed' : 'Plan missed'}
                />
              )}
              <div className="space-y-0.5">
                {dayActivities.map((a) => (
                  <Link key={a.id} to={`/activities/${a.id}`} onClick={e => e.stopPropagation()} className="flex items-center gap-1 group">
                    <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: getSportColor(a.sport_type) }} />
                    <span className={clsx('text-[9px] text-gray-400 truncate leading-tight', isLight ? 'group-hover:text-gray-900' : 'group-hover:text-white')}>{a.name}</span>
                  </Link>
                ))}
              </div>
              {daySessions.map((s) => {
                const sColor = getSportColor(s.sport_type as string)
                return (
                  <div
                    key={s.id as number}
                    className="mt-0.5 text-[9px] px-1 py-0.5 rounded border border-dashed truncate"
                    style={{ borderColor: `${sColor}60`, color: `${sColor}bb` }}
                    title={s.description as string || s.sport_type as string}
                  >
                    {s.description ? `${s.sport_type}: ${s.description}` : s.sport_type as string}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>

      {/* Weekly Report */}
      <section>
        <div className="flex items-center gap-3 mb-4">
          <h3 className="text-lg font-semibold text-gray-300">Weekly Report</h3>
          <ExportButton
            url={`/api/exports/weekly-report?week_start=${weekStart}`}
            label="Export"
            filename={`weekly_report_${weekStart}.png`}
          />
          <div className="flex items-center gap-2">
            <button onClick={() => setWeekOffset(o => o + 1)} className="bg-surface-700 hover:bg-surface-600 px-2 py-1 rounded text-sm">&larr;</button>
            <span className="text-sm text-gray-400 min-w-[140px] text-center">{current?.week_start ?? weekStart}</span>
            <button onClick={() => setWeekOffset(o => Math.max(0, o - 1))} disabled={weekOffset === 0} className="bg-surface-700 hover:bg-surface-600 px-2 py-1 rounded text-sm disabled:opacity-30">&rarr;</button>
          </div>
        </div>

        {weekLoading ? (
          <div className="text-gray-500">Loading...</div>
        ) : current ? (
          <div className="space-y-4">
            {/* Activities this week + Upcoming plan side by side */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Activities this week */}
              <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
                <div className="text-xs text-gray-500 uppercase mb-3">Activities This Week</div>
                {weekActivities?.items && weekActivities.items.length > 0 ? (
                  <div className="space-y-2">
                    {weekActivities.items.map((a: Record<string, unknown>) => {
                      const color = weekSportColors[a.sport_type as string] ?? getSportColor(a.sport_type as string)
                      return (
                        <Link
                          key={a.id as string}
                          to={`/activities/${a.id}`}
                          className={clsx('flex items-center gap-3 px-3 py-2 rounded-lg transition-colors group', isLight ? 'hover:bg-black/[0.04]' : 'hover:bg-white/[0.04]')}
                        >
                          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
                          <span className={clsx('text-sm text-gray-300 truncate flex-1', isLight ? 'group-hover:text-gray-900' : 'group-hover:text-white')}>{a.name as string}</span>
                          <span className="text-xs text-gray-500 shrink-0">{a.sport_type as string}</span>
                          {a.distance_km != null && (
                            <span className="text-xs font-mono shrink-0" style={{ color }}>{(a.distance_km as number).toFixed(1)} km</span>
                          )}
                          {a.moving_time != null && (
                            <span className="text-xs font-mono text-gray-500 shrink-0">{Math.round((a.moving_time as number) / 60)} min</span>
                          )}
                          <span className="text-xs text-gray-600 shrink-0">
                            {a.start_date_local ? new Date(a.start_date_local as string).toLocaleDateString(undefined, { weekday: 'short' }) : ''}
                          </span>
                        </Link>
                      )
                    })}
                  </div>
                ) : (
                  <div className="text-sm text-gray-600">No activities yet</div>
                )}
              </div>

              {/* Upcoming planned sessions */}
              <UpcomingPlan sessions={upcomingSessions} todayStr={todayStr} />
            </div>

            {/* Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
              <StatCard label="Activities" value={current.total_activities} delta={delta('total_activities')} />
              <StatCard label="Distance" value={current.total_distance_km?.toFixed(1)} unit="km" delta={delta('total_distance_km')} />
              <StatCard label="Time" value={current.total_time_hours?.toFixed(1)} unit="hrs" delta={delta('total_time_hours')} />
              <StatCard label="Elevation" value={Math.round(current.total_elevation_m ?? 0)} unit="m" delta={delta('total_elevation_m')} />
              <StatCard label="Active Days" value={current.active_days} delta={delta('active_days')} />
            </div>

            {/* Accumulated Training Time */}
            {current.time_per_sport_per_day_mins && (
              <AccumulatedChart
                data={current.time_per_sport_per_day_mins}
                titles={current.activities_titles_per_day_per_sport}
                colorMap={weekSportColors}
              />
            )}

            {/* HR Zone Distribution */}
            {current.hr_zone_distribution && Object.values(current.hr_zone_distribution).some((v: unknown) => (v as number) > 0) && (
              <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
                <div className="text-xs text-gray-500 uppercase mb-3">HR Zone Distribution</div>
                <div className="flex gap-1 h-6 rounded overflow-hidden">
                  {[1, 2, 3, 4, 5].map(z => {
                    const pct = current.hr_zone_distribution?.[z] ?? 0
                    const colors = ['bg-gray-500', 'bg-blue-500', 'bg-green-500', 'bg-yellow-500', 'bg-red-500']
                    return pct > 0 ? (
                      <div
                        key={z}
                        className={`${colors[z - 1]} flex items-center justify-center text-[10px] font-bold text-white`}
                        style={{ width: `${pct}%` }}
                        title={`Z${z}: ${pct}%`}
                      >
                        {pct > 5 ? `Z${z}` : ''}
                      </div>
                    ) : null
                  })}
                </div>
              </div>
            )}

            {/* Pie charts */}
            {current.distance_per_sport_km && Object.keys(current.distance_per_sport_km).length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <SportPieChart
                  title="Distance (km)"
                  data={current.distance_per_sport_km}
                  formatValue={(v: number) => `${v.toFixed(1)} km`}
                  colorMap={weekSportColors}
                />
                <SportPieChart
                  title="Time (min)"
                  data={Object.fromEntries(
                    Object.entries(current.time_per_sport_hours ?? {}).map(([s, h]) => [s, (h as number) * 60])
                  )}
                  formatValue={(v: number) => `${Math.round(v)} min`}
                  colorMap={weekSportColors}
                />
              </div>
            )}
          </div>
        ) : null}
      </section>

      {/* Session Modal */}
      {showModal && selectedDate && (
        <SessionModal
          date={selectedDate}
          sessions={sessionMap[selectedDate] || []}
          onAdd={handleAddSession}
          onUpdate={handleUpdateSession}
          onDelete={(id: number) => deleteSession.mutate(id)}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  )
}
