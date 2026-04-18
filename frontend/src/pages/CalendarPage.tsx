import { Fragment, useState, useMemo, useRef, useEffect, useCallback, type ReactNode } from 'react'
import {
  startOfMonth, endOfMonth, eachDayOfInterval, format, addMonths, subMonths, addDays, subDays,
  isSameMonth, isToday, startOfWeek, endOfWeek, isSameWeek, parseISO, differenceInDays,
} from 'date-fns'
import { Link } from 'react-router-dom'
import {
  useActivitiesByDateRange, useCalendarSessions, useCalendarSessionsByRange,
  useCreateSession, useUpdateSession, useDeleteSession, useWeeklyReport, useAthleteZones,
  useStreaks, useGoalProgress, useGoals, useSessionScores, useWorkoutTemplates, useCreateWorkoutTemplate,
  useRaceEventsByRange, useUpcomingRaces, useCreateRaceEvent, useUpdateRaceEvent, useDeleteRaceEvent,
} from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { getPaceUnit, getSportCategory, formatDist, getDistUnit } from '../utils/formatSpeed'
import SportTypeCombobox from '../components/shared/SportTypeCombobox'
import StatCard from '../components/shared/StatCard'
import ExportButton from '../components/shared/ExportButton'
import {
  FlagIcon, CheckIcon, DistanceIcon, TimerIcon, BoltIcon, RangeIcon, HeartIcon,
} from '../components/icons'
import clsx from 'clsx'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  PieChart, Pie, Cell,
} from 'recharts'
import { useTheme } from '../hooks/useTheme'
import { useToast } from '../hooks/useToast'
import SegmentListBuilder, { SegmentSummary, type Segment } from '../components/shared/SegmentListBuilder'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/* ── Sport Pie Chart ────────────────────────────────── */
function SportPieChart({ title, data, formatValue, colorMap }: {
  title: string
  data: Record<string, number>
  formatValue: (v: number, sport?: string) => string
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
    <div className={clsx('rounded-xl p-4 border', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
      <div className="eyebrow mb-2">{title}</div>
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
              <Cell key={i} fill={d.color} fillOpacity={0.7} stroke={d.color} strokeWidth={1} strokeOpacity={0.3} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
            itemStyle={{ color: colors.labelColor }}
            formatter={((value: number, name: string) => [formatValue(value, name), name]) as any}
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
      return <circle cx={cx} cy={cy} r={3} fill={color} fillOpacity={0.8} stroke={isLight ? '#e5e5e5' : '#1a1a1a'} strokeWidth={1} />
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
    <div className={clsx('rounded-xl p-4 border', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
      <div className="eyebrow mb-1">Accumulated Training Time</div>
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
            itemStyle={{ color: colors.labelColor }}
            formatter={((value: number, name: string) => [`${value} min`, name]) as any}
          />
          {sports.map(sport => (
            <Area
              key={sport}
              type="monotone"
              dataKey={sport}
              stroke={sportColorMap[sport]}
              strokeOpacity={0.6}
              fill={sportColorMap[sport]}
              fillOpacity={0.08}
              strokeWidth={1.5}
              dot={makeActiveDot(sport, sportColorMap[sport]) as any}
              label={makeLabel(sport, sportColorMap[sport]) as any}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ── Score color helper ────────────────────────────── */
function scoreColor(score: number): string {
  if (score >= 80) return '#22c55e'
  if (score >= 50) return '#eab308'
  return '#ef4444'
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




/* ── Session Modal ──────────────────────────────────── */
function SessionModal({
  date, sessions, scores, races, onAdd, onCopy, onUpdate, onDelete,
  onAddRace, onUpdateRace, onDeleteRace, onClose,
}: {
  date: string
  sessions: Record<string, unknown>[]
  scores: Record<string, Record<string, unknown>> | undefined
  races: Record<string, unknown>[]
  onAdd: (data: Record<string, unknown>) => void
  onCopy: (session: Record<string, unknown>, targetDate: string) => void
  onUpdate: (id: number, data: Record<string, unknown>) => void
  onDelete: (id: number) => void
  onAddRace: (data: Record<string, unknown>) => void
  onUpdateRace: (id: number, data: Record<string, unknown>) => void
  onDeleteRace: (id: number) => void
  onClose: () => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [sportType, setSportType] = useState('Run')
  const [description, setDescription] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [copyingSessionId, setCopyingSessionId] = useState<number | null>(null)
  const [copyMonth, setCopyMonth] = useState(() => startOfMonth(parseISO(date)))
  const [activeGoals, setActiveGoals] = useState<Set<string>>(new Set())
  const [plannedDistanceKm, setPlannedDistanceKm] = useState<string>('')
  const [plannedDurationMins, setPlannedDurationMins] = useState<string>('')
  const [targetAvgPace, setTargetAvgPace] = useState<string>('')
  const [targetPaceMin, setTargetPaceMin] = useState<string>('')
  const [targetPaceMax, setTargetPaceMax] = useState<string>('')
  const [targetHrZone, setTargetHrZone] = useState<string>('')
  const [targetZonePct, setTargetZonePct] = useState<string>('80')
  const [showGoalPicker, setShowGoalPicker] = useState(false)
  const [segments, setSegments] = useState<Segment[]>([])
  const [workoutTemplateId, setWorkoutTemplateId] = useState<number | null>(null)
  const [showTemplatePicker, setShowTemplatePicker] = useState(false)
  const [saveTemplateName, setSaveTemplateName] = useState('')
  const [showSaveTemplate, setShowSaveTemplate] = useState(false)
  // Race event state
  const [showRaceForm, setShowRaceForm] = useState(false)
  const [editingRaceId, setEditingRaceId] = useState<number | null>(null)
  const [raceName, setRaceName] = useState('')
  const [raceSportType, setRaceSportType] = useState('Run')
  const [raceDistanceKm, setRaceDistanceKm] = useState('')
  const [raceTargetPace, setRaceTargetPace] = useState('')
  const [raceDescription, setRaceDescription] = useState('')
  const [raceLocation, setRaceLocation] = useState('')
  const [raceUrl, setRaceUrl] = useState('')
  const [confirmDeleteRaceId, setConfirmDeleteRaceId] = useState<number | null>(null)

  const { data: templates } = useWorkoutTemplates(sportType)
  const createTemplate = useCreateWorkoutTemplate()

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  function startEdit(s: Record<string, unknown>) {
    setEditingId(s.id as number)
    setSportType(s.sport_type as string)
    setDescription((s.description as string) || '')
    const goals = new Set<string>()
    const hasSegments = s.segments && Array.isArray(s.segments) && (s.segments as Segment[]).length > 0
    // Don't show distance as a separate goal if it was auto-computed from segments
    if (s.planned_distance_km != null && !hasSegments) {
      goals.add('distance')
      // Convert km back to meters for swimming display
      const displayDist = getSportCategory(s.sport_type as string) === 'swimming'
        ? (s.planned_distance_km as number) * 1000
        : (s.planned_distance_km as number)
      setPlannedDistanceKm(String(displayDist))
    } else { setPlannedDistanceKm('') }
    if (s.planned_duration_mins != null) { goals.add('duration'); setPlannedDurationMins(String(s.planned_duration_mins)) } else { setPlannedDurationMins('') }
    if (s.target_avg_pace != null) { goals.add('avg_pace'); setTargetAvgPace(String(s.target_avg_pace)) } else { setTargetAvgPace('') }
    if (s.target_pace_min != null || s.target_pace_max != null) { goals.add('pace_range') }
    setTargetPaceMin(s.target_pace_min != null ? String(s.target_pace_min) : '')
    setTargetPaceMax(s.target_pace_max != null ? String(s.target_pace_max) : '')
    if (s.target_hr_zone != null) { goals.add('hr_zone') }
    setTargetHrZone(s.target_hr_zone != null ? String(s.target_hr_zone) : '')
    setTargetZonePct(s.target_zone_pct != null ? String(s.target_zone_pct) : '80')
    if (hasSegments) {
      goals.add('segments')
      setSegments(s.segments as Segment[])
      setWorkoutTemplateId((s.workout_template_id as number) ?? null)
    } else {
      setSegments([])
      setWorkoutTemplateId(null)
    }
    setActiveGoals(goals)
    setShowGoalPicker(false)
    setShowTemplatePicker(false)
  }

  function cancelEdit() {
    setEditingId(null)
    setSportType('Run')
    setDescription('')
    setActiveGoals(new Set())
    setPlannedDistanceKm('')
    setPlannedDurationMins('')
    setTargetAvgPace('')
    setTargetPaceMin('')
    setTargetPaceMax('')
    setTargetHrZone('')
    setTargetZonePct('80')
    setShowGoalPicker(false)
    setSegments([])
    setWorkoutTemplateId(null)
    setShowTemplatePicker(false)
  }

  function buildPayload() {
    const data: Record<string, unknown> = {
      sport_type: sportType,
      description: description || undefined,
    }
    // Distance
    if (activeGoals.has('distance') && plannedDistanceKm) {
      const raw = parseFloat(plannedDistanceKm)
      // User enters meters for swimming, km for others — always store as km
      data.planned_distance_km = getSportCategory(sportType) === 'swimming' ? raw / 1000 : raw
    } else {
      data.planned_distance_km = null
    }
    // Duration
    if (activeGoals.has('duration') && plannedDurationMins) {
      data.planned_duration_mins = parseFloat(plannedDurationMins)
    } else {
      data.planned_duration_mins = null
    }
    // Avg Pace
    if (activeGoals.has('avg_pace') && targetAvgPace) {
      data.target_avg_pace = parseFloat(targetAvgPace)
    } else {
      data.target_avg_pace = null
    }
    // Pace Range
    if (activeGoals.has('pace_range')) {
      data.target_pace_min = targetPaceMin ? parseFloat(targetPaceMin) : null
      data.target_pace_max = targetPaceMax ? parseFloat(targetPaceMax) : null
    } else {
      data.target_pace_min = null
      data.target_pace_max = null
    }
    // HR Zone
    if (activeGoals.has('hr_zone') && targetHrZone) {
      data.target_hr_zone = parseInt(targetHrZone)
      data.target_zone_pct = targetZonePct ? parseFloat(targetZonePct) : 80
    } else {
      data.target_hr_zone = null
      data.target_zone_pct = null
    }
    // Structured Workout
    if (activeGoals.has('segments') && segments.length > 0) {
      data.segments = segments
      data.workout_template_id = workoutTemplateId
      // Auto-compute planned distance from segments for activity matching
      const totalKm = segments.reduce((sum, s) => {
        const dist = s.distance_km ?? 0
        const reps = s.repetitions ?? 1
        const recDist = s.recovery_distance_km ?? 0
        return sum + (dist * reps) + (recDist * Math.max(0, reps - 1))
      }, 0)
      if (totalKm > 0 && !data.planned_distance_km) {
        data.planned_distance_km = Math.round(totalKm * 10) / 10
      }
    } else {
      data.segments = null
      data.workout_template_id = null
    }
    return data
  }

  function addGoal(key: string) {
    setActiveGoals(prev => new Set(prev).add(key))
    setShowGoalPicker(false)
    if (key === 'distance' && !plannedDistanceKm) setPlannedDistanceKm('10')
    if (key === 'duration' && !plannedDurationMins) setPlannedDurationMins('60')
    if (key === 'avg_pace' && !targetAvgPace) {
      setTargetAvgPace(getPaceUnit(sportType) === 'min/km' ? '5.5' : '28')
    }
    if (key === 'pace_range') {
      if (!targetPaceMin) setTargetPaceMin(getPaceUnit(sportType) === 'min/km' ? '5.0' : '25')
      if (!targetPaceMax) setTargetPaceMax(getPaceUnit(sportType) === 'min/km' ? '6.0' : '32')
    }
    if (key === 'hr_zone' && !targetHrZone) setTargetHrZone('2')
  }

  function removeGoal(key: string) {
    setActiveGoals(prev => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
    // Clear values for removed goal
    if (key === 'distance') setPlannedDistanceKm('')
    if (key === 'duration') setPlannedDurationMins('')
    if (key === 'avg_pace') setTargetAvgPace('')
    if (key === 'pace_range') { setTargetPaceMin(''); setTargetPaceMax('') }
    if (key === 'hr_zone') { setTargetHrZone(''); setTargetZonePct('80') }
    if (key === 'segments') { setSegments([]); setWorkoutTemplateId(null); setShowTemplatePicker(false) }
  }

  const paceUnit = getPaceUnit(sportType)
  return (
    <div
      className={clsx('fixed inset-0 flex items-center justify-center z-50 animate-[fadeIn_150ms_ease-out]', isLight ? 'bg-black/30' : 'bg-black/60')}
      onClick={onClose}
    >
      <div
        className={clsx('border rounded-xl p-6 w-full max-w-md max-h-[85vh] overflow-y-auto animate-[scaleIn_150ms_ease-out]', isLight ? 'bg-white border-gray-200 shadow-xl' : 'bg-surface-800 border-surface-600 shadow-xl')}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <div>
            <div className="eyebrow mb-0.5">{format(parseISO(date), 'EEEE')}</div>
            <h3
              className={clsx('text-lg font-semibold tracking-tight tabular-nums', isLight ? 'text-gray-900' : 'text-gray-100')}
              style={{ letterSpacing: '-0.02em' }}
            >
              {format(parseISO(date), 'MMM d, yyyy')}
            </h3>
          </div>
          <button
            onClick={onClose}
            className={clsx('p-1 rounded transition-colors', isLight ? 'text-gray-400 hover:text-gray-700 hover:bg-black/5' : 'text-gray-500 hover:text-gray-200 hover:bg-white/5')}
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12" /></svg>
          </button>
        </div>

        {/* Race Events section */}
        {(races.length > 0 || showRaceForm) && (
          <div className="mb-4 space-y-2">
            <div className="eyebrow flex items-center gap-1.5">
              <span className="text-amber-500"><FlagIcon size={10} /></span> Race events
            </div>
            {races.map(r => {
              const isConfirmingRace = confirmDeleteRaceId === (r.id as number)
              return (
                <div key={r.id as number} className="rounded p-2 border transition-colors"
                  style={{ borderColor: '#f59e0b60', backgroundColor: '#f59e0b08' }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0 cursor-pointer" onClick={() => {
                      setEditingRaceId(r.id as number)
                      setRaceName(r.name as string)
                      setRaceSportType(r.sport_type as string)
                      setRaceDistanceKm(r.distance_km != null ? String(r.distance_km) : '')
                      setRaceTargetPace(r.target_pace != null ? String(r.target_pace) : '')
                      setRaceDescription((r.description as string) || '')
                      setRaceLocation((r.location as string) || '')
                      setRaceUrl((r.url as string) || '')
                      setShowRaceForm(true)
                    }}>
                      <span className="text-amber-500"><FlagIcon size={11} /></span>
                      <span className="text-sm text-amber-500 font-medium">{String(r.name)}</span>
                      {r.distance_km != null && (
                        <span className="text-xs text-gray-400">{r.distance_km as number} km</span>
                      )}
                      {r.location != null && (
                        <span className="text-xs text-gray-500 truncate">{String(r.location)}</span>
                      )}
                    </div>
                    <div className="flex gap-2 shrink-0 ml-2">
                      {isConfirmingRace ? (
                        <>
                          <span className="text-xs text-red-400">Delete?</span>
                          <button onClick={() => { onDeleteRace(r.id as number); setConfirmDeleteRaceId(null) }} className="text-red-400 hover:text-red-300 text-xs font-bold">Yes</button>
                          <button onClick={() => setConfirmDeleteRaceId(null)} className={clsx('text-xs text-gray-400', isLight ? 'hover:text-gray-700' : 'hover:text-gray-200')}>No</button>
                        </>
                      ) : (
                        <>
                          <button onClick={() => {
                            setEditingRaceId(r.id as number)
                            setRaceName(r.name as string)
                            setRaceSportType(r.sport_type as string)
                            setRaceDistanceKm(r.distance_km != null ? String(r.distance_km) : '')
                            setRaceTargetPace(r.target_pace != null ? String(r.target_pace) : '')
                            setRaceDescription((r.description as string) || '')
                            setRaceLocation((r.location as string) || '')
                            setRaceUrl((r.url as string) || '')
                            setShowRaceForm(true)
                          }} className={clsx('text-gray-400 text-xs', isLight ? 'hover:text-gray-700' : 'hover:text-gray-200')}>Edit</button>
                          <button onClick={() => setConfirmDeleteRaceId(r.id as number)} className="text-red-400 hover:text-red-300 text-xs">Delete</button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
            {showRaceForm && (
              <div className="space-y-2 pt-1">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Race Name</label>
                  <input
                    type="text" placeholder="e.g. Berlin Marathon"
                    value={raceName} onChange={e => setRaceName(e.target.value)}
                    className={clsx('w-full border rounded-lg px-3 py-2 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                    autoFocus
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Sport</label>
                    <SportTypeCombobox
                      value={raceSportType}
                      onChange={setRaceSportType}
                      className={clsx('w-full border rounded-lg px-3 py-2 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                      isLight={isLight}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Distance (km)</label>
                    <input
                      type="text" inputMode="decimal" placeholder="42.195"
                      value={raceDistanceKm} onChange={e => setRaceDistanceKm(e.target.value)}
                      className={clsx('w-full border rounded-lg px-3 py-2 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Target Pace ({getPaceUnit(raceSportType)})</label>
                    <input
                      type="text" inputMode="decimal" placeholder={getPaceUnit(raceSportType) === 'min/km' ? '5:00' : '30'}
                      value={raceTargetPace} onChange={e => setRaceTargetPace(e.target.value)}
                      className={clsx('w-full border rounded-lg px-3 py-2 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Location</label>
                    <input
                      type="text" placeholder="Berlin, Germany"
                      value={raceLocation} onChange={e => setRaceLocation(e.target.value)}
                      className={clsx('w-full border rounded-lg px-3 py-2 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                    />
                  </div>
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">URL</label>
                  <input
                    type="text" placeholder="https://..."
                    value={raceUrl} onChange={e => setRaceUrl(e.target.value)}
                    className={clsx('w-full border rounded-lg px-3 py-2 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Notes</label>
                  <textarea
                    placeholder="Race notes..."
                    value={raceDescription} onChange={e => setRaceDescription(e.target.value)}
                    className={clsx('w-full border rounded-lg px-3 py-2 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                    rows={2}
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      if (!raceName.trim()) return
                      const payload: Record<string, unknown> = {
                        name: raceName.trim(),
                        sport_type: raceSportType,
                        distance_km: raceDistanceKm ? parseFloat(raceDistanceKm) : null,
                        target_pace: raceTargetPace ? parseFloat(raceTargetPace) : null,
                        description: raceDescription || null,
                        location: raceLocation || null,
                        url: raceUrl || null,
                      }
                      if (editingRaceId) {
                        onUpdateRace(editingRaceId, payload)
                      } else {
                        onAddRace(payload)
                      }
                      setShowRaceForm(false)
                      setEditingRaceId(null)
                      setRaceName(''); setRaceDistanceKm(''); setRaceTargetPace('')
                      setRaceDescription(''); setRaceLocation(''); setRaceUrl('')
                    }}
                    className={clsx('flex-1 rounded py-2 text-sm font-medium transition-colors', 'bg-amber-500/20 text-amber-500 border border-amber-500/30 hover:bg-amber-500/30')}
                  >
                    {editingRaceId ? 'Save Race' : 'Add Race'}
                  </button>
                  <button onClick={() => {
                    setShowRaceForm(false); setEditingRaceId(null)
                    setRaceName(''); setRaceDistanceKm(''); setRaceTargetPace('')
                    setRaceDescription(''); setRaceLocation(''); setRaceUrl('')
                  }} className={clsx('flex-1 rounded py-2 text-sm text-gray-400', isLight ? 'bg-gray-100 hover:text-gray-700' : 'bg-surface-700 hover:text-gray-200')}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
        {!showRaceForm && (
          <button
            onClick={() => { setShowRaceForm(true); setEditingRaceId(null) }}
            className="mb-3 text-[11px] uppercase tracking-[0.15em] flex items-center gap-1.5 text-amber-500/70 hover:text-amber-500 transition-colors"
          >
            <FlagIcon size={10} /> Add race event
          </button>
        )}

        {sessions.length > 0 && (
          <div className="mb-4 space-y-2">
            <div className="eyebrow">Planned Sessions</div>
            {sessions.map(s => {
              const sColor = getSportColor(s.sport_type as string)
              const isConfirming = confirmDeleteId === (s.id as number)
              const sessionScore = scores?.[String(s.id as number)]
              return (
                <div key={s.id as number}>
                  <div className="rounded p-2 border border-dashed transition-colors"
                    style={{ borderColor: `${sColor}60`, backgroundColor: `${sColor}10` }}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 min-w-0 cursor-pointer" onClick={() => startEdit(s)}>
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: sColor }} />
                        <span className="text-sm" style={{ color: sColor }}>{String(s.sport_type)}</span>
                        {!!s.description && (
                          <span className="text-xs text-gray-400 truncate">{String(s.description)}</span>
                        )}
                        {sessionScore && (
                          <span
                            className="text-xs font-bold font-mono px-1.5 py-0.5 rounded"
                            style={{ color: scoreColor(sessionScore.overall_score as number), backgroundColor: `${scoreColor(sessionScore.overall_score as number)}15` }}
                          >
                            {sessionScore.overall_score as number}
                          </span>
                        )}
                      </div>
                      <div className="flex gap-2 shrink-0 ml-2">
                        {isConfirming ? (
                          <>
                            <span className="text-xs text-red-400">Delete?</span>
                            <button onClick={() => { onDelete(s.id as number); setConfirmDeleteId(null) }} className="text-red-400 hover:text-red-300 text-xs font-bold">Yes</button>
                            <button onClick={() => setConfirmDeleteId(null)} className={clsx('text-xs text-gray-400', isLight ? 'hover:text-gray-700' : 'hover:text-gray-200')}>No</button>
                          </>
                        ) : (
                          <>
                            <button onClick={() => setCopyingSessionId(copyingSessionId === (s.id as number) ? null : s.id as number)} className={clsx('text-xs', copyingSessionId === (s.id as number) ? 'text-blue-400' : 'text-gray-400', isLight ? 'hover:text-gray-700' : 'hover:text-gray-200')}>Copy</button>
                            <button onClick={() => startEdit(s)} className={clsx('text-gray-400 text-xs', isLight ? 'hover:text-gray-700' : 'hover:text-gray-200')}>Edit</button>
                            <button onClick={() => setConfirmDeleteId(s.id as number)} className="text-red-400 hover:text-red-300 text-xs">Delete</button>
                          </>
                        )}
                      </div>
                    </div>
                    {/* Segment summary */}
                    {!!s.segments && Array.isArray(s.segments) && (s.segments as Segment[]).length > 0 && (
                      <div className="mt-1.5">
                        <SegmentSummary segments={s.segments as Segment[]} />
                      </div>
                    )}
                  </div>
                  {copyingSessionId === (s.id as number) && (() => {
                    const mStart = startOfWeek(startOfMonth(copyMonth), { weekStartsOn: 1 })
                    const mEnd = endOfWeek(endOfMonth(copyMonth), { weekStartsOn: 1 })
                    const mDays = eachDayOfInterval({ start: mStart, end: mEnd })
                    return (
                      <div className={clsx('mt-1 p-2 border rounded-lg', isLight ? 'bg-gray-50 border-gray-200' : 'bg-surface-700/50 border-surface-600')}>
                        <div className="flex items-center justify-between mb-2">
                          <button onClick={() => setCopyMonth(m => subMonths(m, 1))} className="text-gray-400 hover:text-gray-200 text-xs px-1">&lt;</button>
                          <span className="text-xs text-gray-300 font-medium">{format(copyMonth, 'MMM yyyy')}</span>
                          <button onClick={() => setCopyMonth(m => addMonths(m, 1))} className="text-gray-400 hover:text-gray-200 text-xs px-1">&gt;</button>
                        </div>
                        <div className="grid grid-cols-7 gap-0.5 text-center">
                          {['M','T','W','T','F','S','S'].map((d, i) => (
                            <div key={i} className="text-[9px] text-gray-600 py-0.5">{d}</div>
                          ))}
                          {mDays.map(d => {
                            const ds = format(d, 'yyyy-MM-dd')
                            const inM = isSameMonth(d, copyMonth)
                            const isCurrent = ds === date
                            return (
                              <button
                                key={ds}
                                disabled={isCurrent}
                                onClick={() => {
                                  onCopy(s, ds)
                                  setCopyingSessionId(null)
                                }}
                                className={clsx(
                                  'text-[10px] py-1 rounded transition-colors',
                                  isCurrent ? 'text-gray-600 cursor-not-allowed' : 'hover:bg-blue-400/20 hover:text-blue-400',
                                  inM ? 'text-gray-400' : 'text-gray-600',
                                  isToday(d) && 'font-bold text-gray-100',
                                )}
                              >
                                {format(d, 'd')}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })()}
                </div>
              )
            })}
          </div>
        )}

        <div className="space-y-3">
          <div className="eyebrow">
            {editingId ? 'Edit Session' : 'Add Session'}
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Session Type</label>
            <SportTypeCombobox
              value={sportType}
              onChange={setSportType}
              className={clsx('w-full border rounded-lg px-4 py-3.5', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
              isLight={isLight}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Description</label>
            <textarea
              placeholder="e.g. Easy 10k recovery run"
              value={description}
              onChange={e => setDescription(e.target.value)}
              className={clsx('w-full border rounded-lg px-3 py-2.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
              rows={3}
            />
          </div>

          {/* Goal cards */}
          {activeGoals.size > 0 && (
            <div className="space-y-2">
              {activeGoals.has('distance') && (
                <div className="flex rounded-lg overflow-hidden border" style={{ borderColor: '#3b82f620' }}>
                  <div className="w-1 shrink-0" style={{ backgroundColor: '#3b82f6' }} />
                  <div className="flex-1 p-2.5" style={{ backgroundColor: '#3b82f608' }}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium flex items-center gap-1.5" style={{ color: '#3b82f6' }}>
                        <DistanceIcon size={11} /> Distance
                      </span>
                      <button onClick={() => removeGoal('distance')} className="text-gray-500 hover:text-gray-300 text-xs leading-none px-1">✕</button>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="text" inputMode="decimal" placeholder="10"
                        value={plannedDistanceKm} onChange={e => setPlannedDistanceKm(e.target.value)}
                        className={clsx('w-24 border rounded px-2 py-1.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                      />
                      <span className="text-xs text-gray-500">{getDistUnit(sportType)}</span>
                    </div>
                  </div>
                </div>
              )}

              {activeGoals.has('duration') && (
                <div className="flex rounded-lg overflow-hidden border" style={{ borderColor: '#22c55e20' }}>
                  <div className="w-1 shrink-0" style={{ backgroundColor: '#22c55e' }} />
                  <div className="flex-1 p-2.5" style={{ backgroundColor: '#22c55e08' }}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium flex items-center gap-1.5" style={{ color: '#22c55e' }}>
                        <TimerIcon size={11} /> Duration
                      </span>
                      <button onClick={() => removeGoal('duration')} className="text-gray-500 hover:text-gray-300 text-xs leading-none px-1">✕</button>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="text" inputMode="decimal" placeholder="60"
                        value={plannedDurationMins} onChange={e => setPlannedDurationMins(e.target.value)}
                        className={clsx('w-24 border rounded px-2 py-1.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                      />
                      <span className="text-xs text-gray-500">min</span>
                    </div>
                  </div>
                </div>
              )}

              {activeGoals.has('avg_pace') && (
                <div className="flex rounded-lg overflow-hidden border" style={{ borderColor: '#f9731620' }}>
                  <div className="w-1 shrink-0" style={{ backgroundColor: '#f97316' }} />
                  <div className="flex-1 p-2.5" style={{ backgroundColor: '#f9731608' }}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium flex items-center gap-1.5" style={{ color: '#f97316' }}>
                        <BoltIcon size={11} /> Avg Pace
                      </span>
                      <button onClick={() => removeGoal('avg_pace')} className="text-gray-500 hover:text-gray-300 text-xs leading-none px-1">✕</button>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '5:10' : '28'}
                        value={targetAvgPace} onChange={e => setTargetAvgPace(e.target.value)}
                        className={clsx('w-24 border rounded px-2 py-1.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                      />
                      <span className="text-xs text-gray-500">{paceUnit}</span>
                    </div>
                  </div>
                </div>
              )}

              {activeGoals.has('pace_range') && (
                <div className="flex rounded-lg overflow-hidden border" style={{ borderColor: '#a855f720' }}>
                  <div className="w-1 shrink-0" style={{ backgroundColor: '#a855f7' }} />
                  <div className="flex-1 p-2.5" style={{ backgroundColor: '#a855f708' }}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium flex items-center gap-1.5" style={{ color: '#a855f7' }}>
                        <RangeIcon size={11} /> Pace Range
                      </span>
                      <button onClick={() => removeGoal('pace_range')} className="text-gray-500 hover:text-gray-300 text-xs leading-none px-1">✕</button>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="eyebrow mb-1 block">
                          {paceUnit === 'min/km' ? 'Fastest' : 'Min speed'} ({paceUnit})
                        </label>
                        <input
                          type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '4:50' : '25'}
                          value={targetPaceMin} onChange={e => setTargetPaceMin(e.target.value)}
                          className={clsx('w-full border rounded px-2 py-1.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                        />
                      </div>
                      <div>
                        <label className="eyebrow mb-1 block">
                          {paceUnit === 'min/km' ? 'Slowest' : 'Max speed'} ({paceUnit})
                        </label>
                        <input
                          type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '5:20' : '32'}
                          value={targetPaceMax} onChange={e => setTargetPaceMax(e.target.value)}
                          className={clsx('w-full border rounded px-2 py-1.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {activeGoals.has('hr_zone') && (
                <div className="flex rounded-lg overflow-hidden border" style={{ borderColor: '#ef444420' }}>
                  <div className="w-1 shrink-0" style={{ backgroundColor: '#ef4444' }} />
                  <div className="flex-1 p-2.5" style={{ backgroundColor: '#ef444408' }}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium flex items-center gap-1.5" style={{ color: '#ef4444' }}>
                        <HeartIcon size={11} /> HR Zone
                      </span>
                      <button onClick={() => removeGoal('hr_zone')} className="text-gray-500 hover:text-gray-300 text-xs leading-none px-1">✕</button>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="eyebrow mb-1 block">Zone</label>
                        <select
                          value={targetHrZone} onChange={e => setTargetHrZone(e.target.value)}
                          className={clsx('w-full border rounded px-2 py-1.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                        >
                          <option value="">Select</option>
                          {[1, 2, 3, 4, 5].map(z => <option key={z} value={z}>Zone {z}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="eyebrow mb-1 block">Target %</label>
                        <input
                          type="text" inputMode="decimal" placeholder="80"
                          value={targetZonePct} onChange={e => setTargetZonePct(e.target.value)}
                          className={clsx('w-full border rounded px-2 py-1.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {activeGoals.has('segments') && (
                <div className="flex rounded-lg overflow-hidden border" style={{ borderColor: '#22d3ee20' }}>
                  <div className="w-1 shrink-0" style={{ backgroundColor: '#22d3ee' }} />
                  <div className="flex-1 p-2.5" style={{ backgroundColor: '#22d3ee08' }}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium flex items-center gap-1.5" style={{ color: '#22d3ee' }}>
                        Structured Workout
                      </span>
                      <button onClick={() => removeGoal('segments')} className="text-gray-500 hover:text-gray-300 text-xs leading-none px-1">{'\u2715'}</button>
                    </div>
                    {/* Template picker */}
                    <div className="mb-2">
                      <button
                        onClick={() => setShowTemplatePicker(v => !v)}
                        className="text-[11px] rounded px-2 py-1 border transition-all"
                        style={{ borderColor: '#22d3ee40', color: '#22d3ee', backgroundColor: '#22d3ee10' }}
                      >
                        {showTemplatePicker ? 'Hide templates' : 'Pick from library'}
                      </button>
                      {showTemplatePicker && templates && (templates as Record<string, unknown>[]).length > 0 && (
                        <div className="mt-1.5 space-y-1 max-h-32 overflow-y-auto">
                          {(templates as Record<string, unknown>[]).map(t => (
                            <button
                              key={t.id as number}
                              onClick={() => {
                                setSegments((t.segments as Segment[]) || [])
                                setWorkoutTemplateId(t.id as number)
                                setShowTemplatePicker(false)
                              }}
                              className={clsx(
                                'w-full text-left text-xs rounded px-2 py-1.5 border transition-colors',
                                workoutTemplateId === (t.id as number)
                                  ? 'border-blue-400/40 bg-blue-400/10 text-blue-400'
                                  : 'border-surface-600 hover:border-surface-500 text-gray-300'
                              )}
                            >
                              <div className="font-medium">{t.name as string}</div>
                              <SegmentSummary segments={(t.segments as Segment[]) || []} />
                            </button>
                          ))}
                        </div>
                      )}
                      {showTemplatePicker && (!templates || (templates as Record<string, unknown>[]).length === 0) && (
                        <div className="text-[10px] text-gray-500 mt-1">No templates for {sportType}</div>
                      )}
                    </div>
                    <SegmentListBuilder
                      segments={segments}
                      onChange={setSegments}
                      paceUnit={paceUnit}
                      sportType={sportType}
                      compact
                    />
                    {/* Save as template */}
                    {segments.length > 0 && (
                      <div className="mt-2">
                        {!showSaveTemplate ? (
                          <button
                            onClick={() => { setShowSaveTemplate(true); setSaveTemplateName(description || '') }}
                            className="text-[11px] rounded px-2 py-1 border transition-all"
                            style={{ borderColor: '#a855f740', color: '#a855f7', backgroundColor: '#a855f710' }}
                          >
                            Save as template
                          </button>
                        ) : (
                          <div className="flex items-center gap-1.5">
                            <input
                              type="text"
                              placeholder="Template name"
                              value={saveTemplateName}
                              onChange={e => setSaveTemplateName(e.target.value)}
                              className={clsx('flex-1 border rounded px-2 py-1 text-xs placeholder-gray-500', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600 text-gray-100')}
                              autoFocus
                              onKeyDown={e => {
                                if (e.key === 'Enter' && saveTemplateName.trim()) {
                                  createTemplate.mutate({ name: saveTemplateName.trim(), sport_type: sportType, segments: segments as unknown as Record<string, unknown>[] })
                                  setShowSaveTemplate(false)
                                  setSaveTemplateName('')
                                }
                                if (e.key === 'Escape') { setShowSaveTemplate(false) }
                              }}
                            />
                            <button
                              onClick={() => {
                                if (!saveTemplateName.trim()) return
                                createTemplate.mutate({ name: saveTemplateName.trim(), sport_type: sportType, segments: segments as unknown as Record<string, unknown>[] })
                                setShowSaveTemplate(false)
                                setSaveTemplateName('')
                              }}
                              className="text-[11px] rounded px-2 py-1 border transition-all"
                              style={{ borderColor: '#22c55e40', color: '#22c55e', backgroundColor: '#22c55e10' }}
                            >
                              Save
                            </button>
                            <button
                              onClick={() => setShowSaveTemplate(false)}
                              className="text-gray-500 hover:text-gray-300 text-xs px-1"
                            >
                              {'\u2715'}
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Add Goal button + chip picker */}
          <div>
            <button
              onClick={() => setShowGoalPicker(v => !v)}
              className="text-xs flex items-center gap-1 transition-colors rounded-md px-2 py-1"
              style={{
                color: showGoalPicker ? '#ef4444' : '#9ca3af',
                backgroundColor: showGoalPicker ? '#ef444410' : 'transparent',
              }}
            >
              <span className="text-sm">{showGoalPicker ? '−' : '+'}</span>
              <span>{showGoalPicker ? 'Cancel' : 'Add Goal'}</span>
            </button>
            {showGoalPicker && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {([
                  { key: 'distance', label: 'Distance', color: '#3b82f6', icon: <DistanceIcon size={10} /> },
                  { key: 'duration', label: 'Duration', color: '#22c55e', icon: <TimerIcon size={10} /> },
                  { key: 'avg_pace', label: 'Avg Pace', color: '#f97316', icon: <BoltIcon size={10} /> },
                  { key: 'pace_range', label: 'Pace Range', color: '#a855f7', icon: <RangeIcon size={10} /> },
                  { key: 'hr_zone', label: 'HR Zone', color: '#ef4444', icon: <HeartIcon size={10} /> },
                  { key: 'segments', label: 'Structured', color: '#22d3ee', icon: null },
                ] as const).map(g => {
                  const isActive = activeGoals.has(g.key)
                  return (
                    <button
                      key={g.key}
                      disabled={isActive}
                      onClick={() => addGoal(g.key)}
                      className="text-xs rounded-full px-2.5 py-1 border transition-all inline-flex items-center gap-1.5"
                      style={{
                        borderColor: isActive ? '#4b5563' : `${g.color}50`,
                        color: isActive ? '#6b7280' : g.color,
                        backgroundColor: isActive ? 'transparent' : `${g.color}10`,
                        opacity: isActive ? 0.5 : 1,
                        cursor: isActive ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {g.icon} {g.label}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <div className="flex gap-2 pt-2">
            <button
              onClick={() => {
                const payload = buildPayload()
                if (editingId) {
                  onUpdate(editingId, payload)
                  cancelEdit()
                } else {
                  onAdd(payload)
                  setDescription('')
                  setActiveGoals(new Set())
                  setPlannedDistanceKm('')
                  setPlannedDurationMins('')
                  setTargetAvgPace('')
                  setTargetPaceMin('')
                  setTargetPaceMax('')
                  setTargetHrZone('')
                  setTargetZonePct('80')
                  setShowGoalPicker(false)
                  setSegments([])
                  setWorkoutTemplateId(null)
                  setShowTemplatePicker(false)
                }
              }}
              className={clsx('flex-1 rounded py-2 text-sm font-medium transition-colors', isLight ? 'bg-gray-900 text-white hover:bg-gray-800' : 'bg-white/15 text-gray-100 border border-white/20 hover:bg-white/20')}
            >
              {editingId ? 'Save' : 'Add'}
            </button>
            {editingId ? (
              <button onClick={cancelEdit} className={clsx('flex-1 rounded py-2 text-sm text-gray-400', isLight ? 'bg-gray-100 hover:text-gray-700' : 'bg-surface-700 hover:text-gray-200')}>
                Cancel Edit
              </button>
            ) : (
              <button onClick={onClose} className={clsx('flex-1 rounded py-2 text-sm text-gray-400', isLight ? 'bg-gray-100 hover:text-gray-700' : 'bg-surface-700 hover:text-gray-200')}>
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
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [expandedId, setExpandedId] = useState<number | null>(null)

  return (
    <div className={clsx('rounded-xl p-4 border', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
      <div className="eyebrow mb-3">Upcoming Plan (7 days)</div>
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
                  const goals: { icon: ReactNode; color: string; label: string }[] = []
                  const cardHasSegments = s.segments && Array.isArray(s.segments) && (s.segments as Segment[]).length > 0
                  if (s.planned_distance_km != null && !cardHasSegments) goals.push({ icon: <DistanceIcon size={10} />, color: '#3b82f6', label: formatDist(s.planned_distance_km as number, s.sport_type as string) })
                  if (s.planned_duration_mins != null) goals.push({ icon: <TimerIcon size={10} />, color: '#22c55e', label: `${s.planned_duration_mins} min` })
                  if (s.target_avg_pace != null) {
                    const pu = getPaceUnit(s.sport_type as string)
                    goals.push({ icon: <BoltIcon size={10} />, color: '#f97316', label: `${s.target_avg_pace} ${pu}` })
                  }
                  if (s.target_pace_min != null || s.target_pace_max != null) {
                    const pu = getPaceUnit(s.sport_type as string)
                    const isRun = pu === 'min/km'
                    const parts: string[] = []
                    if (s.target_pace_min != null) parts.push(`${isRun ? 'fastest' : 'min'} ${s.target_pace_min}`)
                    if (s.target_pace_max != null) parts.push(`${isRun ? 'slowest' : 'max'} ${s.target_pace_max}`)
                    goals.push({ icon: <RangeIcon size={10} />, color: '#a855f7', label: `${parts.join(' – ')} ${pu}` })
                  }
                  if (s.target_hr_zone != null) {
                    const pct = s.target_zone_pct ?? 80
                    goals.push({ icon: <HeartIcon size={10} />, color: '#ef4444', label: `Zone ${s.target_hr_zone} @ ${pct}%` })
                  }
                  return (
                    <div className="px-3 pb-3 pt-1 border-t border-dashed" style={{ borderColor: `${color}20` }}>
                      {!!s.description && (
                        <p className="text-sm text-gray-300 whitespace-pre-wrap">
                          {String(s.description)}
                        </p>
                      )}
                      {goals.length > 0 && (
                        <div className={clsx('flex flex-wrap gap-1.5', !!s.description && 'mt-2')}>
                          {goals.map((g, i) => (
                            <span
                              key={i}
                              className="text-[11px] rounded-full px-2 py-0.5 border font-mono tabular-nums inline-flex items-center gap-1.5"
                              style={{ color: g.color, borderColor: `${g.color}40`, backgroundColor: `${g.color}10` }}
                            >
                              {g.icon} {g.label}
                            </span>
                          ))}
                        </div>
                      )}
                      {!!s.segments && Array.isArray(s.segments) && (s.segments as Segment[]).length > 0 && (
                        <div className={clsx('mt-2')}>
                          <SegmentSummary segments={s.segments as Segment[]} />
                        </div>
                      )}
                      {!s.description && goals.length === 0 && !(s.segments && Array.isArray(s.segments) && (s.segments as Segment[]).length > 0) && (
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
        <div className="text-sm text-gray-500">No upcoming sessions</div>
      )}
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
        {['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'].map(d => <span key={d} className="eyebrow text-[9px]">{d}</span>)}
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

/* ── Calendar Page ──────────────────────────────────── */
export default function CalendarPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()
  const [currentMonth, setCurrentMonth] = useState(new Date())
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)
  const [showMonthPicker, setShowMonthPicker] = useState(false)
  const [draggingSessionId, setDraggingSessionId] = useState<number | null>(null)
  const [draggingSession, setDraggingSession] = useState<Record<string, unknown> | null>(null)
  const [dragOverDate, setDragOverDate] = useState<string | null>(null)

  const showToast = useCallback((msg: string) => {
    toast(msg, 'success')
  }, [toast])

  const { data: streakData } = useStreaks()
  const { data: calGoals } = useGoals(currentMonth.getFullYear())

  const month = currentMonth.getMonth() + 1
  const year = currentMonth.getFullYear()

  const monthStart = startOfMonth(currentMonth)
  const monthEnd = endOfMonth(currentMonth)
  const calStart = startOfWeek(monthStart, { weekStartsOn: 1 })
  const calEnd = endOfWeek(monthEnd, { weekStartsOn: 1 })
  const days = eachDayOfInterval({ start: calStart, end: calEnd })

  const dateFrom = format(calStart, 'yyyy-MM-dd')
  const dateTo = format(calEnd, 'yyyy-MM-dd')

  const { data: activitiesData, isLoading: activitiesLoading } = useActivitiesByDateRange(dateFrom, dateTo)
  const { data: sessions } = useCalendarSessions(month, year)
  const { data: sessionScores } = useSessionScores(dateFrom, dateTo)
  const createSession = useCreateSession()
  const updateSession = useUpdateSession()
  const deleteSession = useDeleteSession()
  const { data: raceEventsRange } = useRaceEventsByRange(dateFrom, dateTo)
  const { data: upcomingRaces } = useUpcomingRaces()
  const createRace = useCreateRaceEvent()
  const updateRace = useUpdateRaceEvent()
  const deleteRace = useDeleteRaceEvent()

  // Weekly report
  const [weekStart, setWeekStart] = useState(() =>
    format(startOfWeek(new Date(), { weekStartsOn: 1 }), 'yyyy-MM-dd')
  )
  const [showWeekPicker, setShowWeekPicker] = useState(false)
  const thisWeekStart = format(startOfWeek(new Date(), { weekStartsOn: 1 }), 'yyyy-MM-dd')
  const isCurrentWeek = weekStart === thisWeekStart
  const { data: weekData, isLoading: weekLoading } = useWeeklyReport(weekStart)
  const { data: athleteZones } = useAthleteZones()
  const hrZoneBounds = athleteZones?.heart_rate?.zones as { min: number; max: number }[] | undefined
  const current = weekData?.current
  const previous = weekData?.previous

  const { data: weekActivities } = useActivitiesByDateRange(current?.week_start, current?.week_end)
  const { data: goalProgressData } = useGoalProgress(weekStart)

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
    if (c == null || c === 0) return null
    if (!p || p === 0) return 'new'
    return ((c - p) / p) * 100
  }

  // Build maps
  const activityMap = useMemo(() => {
    const map: Record<string, Array<{ id: number; name: string; sport_type: string; distance_km: number; moving_time?: number }>> = {}
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

  const raceMap = useMemo(() => {
    const map: Record<string, Array<Record<string, unknown>>> = {}
    if (raceEventsRange) {
      for (const r of raceEventsRange) {
        if (!map[r.date]) map[r.date] = []
        map[r.date].push(r)
      }
    }
    return map
  }, [raceEventsRange])

  function handleAddSession(data: Record<string, unknown>) {
    if (!selectedDate) return
    createSession.mutate({ date: selectedDate, title: data.sport_type as string, ...data })
  }

  function handleCopySession(session: Record<string, unknown>, targetDate: string) {
    const copyFields = [
      'sport_type', 'description',
      'planned_distance_km', 'planned_duration_mins', 'planned_intensity',
      'target_avg_pace', 'target_pace_min', 'target_pace_max',
      'target_hr_zone', 'target_zone_pct',
    ]
    const data: Record<string, unknown> = { date: targetDate, title: session.sport_type as string }
    for (const f of copyFields) {
      if (session[f] != null) data[f] = session[f]
    }
    createSession.mutate(data)
    showToast(`Session copied to ${format(parseISO(targetDate), 'EEE, MMM d')}`)
  }

  function handleUpdateSession(id: number, data: Record<string, unknown>) {
    updateSession.mutate({ id, title: data.sport_type as string, ...data })
  }

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
          <div className="flex items-center gap-1.5 relative">
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
          </div>
        </div>
        {/* Streak badges */}
        {streakData && (streakData.current_streak > 0 || streakData.longest_streak > 0 || streakData.current_week_streak > 0 || streakData.longest_week_streak > 0) && (
          <div className="flex items-center gap-1.5 flex-wrap">
            {streakData.current_streak > 0 && (
              <StreakBadge
                value={streakData.current_streak}
                label={`day${streakData.current_streak !== 1 ? 's' : ''}`}
                kind="current"
                title="Current streak — consecutive days with activities"
              />
            )}
            {streakData.longest_streak > 0 && (
              <StreakBadge
                value={streakData.longest_streak}
                label="best days"
                kind="best"
                title={`Longest day streak: ${streakData.longest_streak_start} to ${streakData.longest_streak_end}`}
              />
            )}
            {streakData.current_week_streak > 0 && (
              <StreakBadge
                value={streakData.current_week_streak}
                label={`wk${streakData.current_week_streak !== 1 ? 's' : ''}`}
                kind="current"
                title="Current streak — consecutive weeks with activities"
              />
            )}
            {streakData.longest_week_streak > 0 && (
              <StreakBadge
                value={streakData.longest_week_streak}
                label="best wks"
                kind="best"
                title={`Longest week streak: ${streakData.longest_week_streak_start} to ${streakData.longest_week_streak_end}`}
              />
            )}
          </div>
        )}

        {/* Race countdown banner */}
        {upcomingRaces && upcomingRaces.length > 0 && (() => {
          const nextRace = upcomingRaces[0]
          const daysUntil = differenceInDays(parseISO(nextRace.date), new Date()) + 1
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
                <div
                  className="text-xl font-mono tabular-nums font-bold leading-none"
                  style={{ color: '#eab308', letterSpacing: '-0.02em' }}
                >
                  {daysUntil}
                </div>
                <div className="eyebrow mt-0.5 text-[9px]" style={{ color: '#eab308cc' }}>
                  day{daysUntil !== 1 ? 's' : ''}
                </div>
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
                  {nextRace.distance_km && <span>{nextRace.distance_km} km</span>}
                  {nextRace.location && <span className="normal-case">{nextRace.location}</span>}
                  <span>{format(parseISO(nextRace.date), 'MMM d, yyyy')}</span>
                </div>
              </div>
              {upcomingRaces.length > 1 && (
                <div className="hidden md:flex items-center gap-1 shrink-0">
                  {upcomingRaces.slice(1, 4).map((r: Record<string, unknown>) => {
                    const d = differenceInDays(parseISO(r.date as string), new Date()) + 1
                    return (
                      <div
                        key={r.id as number}
                        className={clsx(
                          'flex items-center gap-1 border rounded-lg px-2 py-0.5',
                          isLight ? 'bg-white border-amber-200' : 'bg-surface-800 border-amber-500/20',
                        )}
                        title={`${r.name}: ${format(parseISO(r.date as string), 'MMM d, yyyy')}`}
                      >
                        <span className="text-[11px] font-mono tabular-nums font-semibold text-amber-500">{d}d</span>
                        <span className="text-[10px] text-gray-500 truncate max-w-[72px]">{r.name as string}</span>
                      </div>
                    )
                  })}
                </div>
              )}
            </Link>
          )
        })()}
      </header>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-1" key={format(currentMonth, 'yyyy-MM')} style={{ animation: 'fadeIn 200ms ease-out' }}>
        {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(d => (
          <div key={d} className="eyebrow text-center py-1.5">{d}</div>
        ))}

        {activitiesLoading ? (
          <>
            {Array.from({ length: 35 }).map((_, i) => (
              <div key={i} className={clsx('min-h-[120px] rounded-lg border animate-pulse', isLight ? 'bg-gray-100 border-gray-200' : 'bg-surface-800 border-surface-600')}>
                <div className="p-2">
                  <div className="h-3 w-4 bg-surface-600 rounded mb-2" />
                  <div className="space-y-1">
                    <div className="h-2 w-3/4 bg-surface-600 rounded" />
                    <div className="h-2 w-1/2 bg-surface-600 rounded" />
                  </div>
                </div>
              </div>
            ))}
          </>
        ) : days.map((day, idx) => {
          const dateStr = format(day, 'yyyy-MM-dd')
          const dayActivities = activityMap[dateStr] || []
          const daySessions = sessionMap[dateStr] || []
          const inMonth = isSameMonth(day, currentMonth)
          const isPastOrToday = day <= new Date(new Date().setHours(23, 59, 59, 999))

          let planStatus: 'done' | 'missed' | null = null
          if (daySessions.length > 0 && isPastOrToday) {
            const activitySports = new Set(dayActivities.map(a => a.sport_type))
            const allMatched = daySessions.every(s => {
              const sport = (s.sport_type as string).toLowerCase()
              if (sport === 'rest') return dayActivities.length === 0
              return activitySports.has(s.sport_type as string)
            })
            planStatus = allMatched ? 'done' : 'missed'
          }

          const weekSummary = idx % 7 === 0 ? (() => {
            const weekDays = days.slice(idx, idx + 7)
            let totalKm = 0
            let totalSec = 0
            for (const wd of weekDays) {
              const ds = format(wd, 'yyyy-MM-dd')
              const acts = activityMap[ds] || []
              for (const a of acts) {
                totalKm += a.distance_km ?? 0
                totalSec += a.moving_time ?? 0
              }
            }
            const totalMin = Math.floor(totalSec / 60)
            const h = Math.floor(totalMin / 60)
            const m = totalMin % 60
            const timeStr = h > 0 ? `${h}h ${m}m` : `${m}m`

            // Compute weekly goal progress client-side for this week row
            const weeklyGoalProgress = (calGoals ?? [])
              .filter((g: Record<string, unknown>) => g.period === 'weekly')
              .map((g: Record<string, unknown>) => {
                let current = 0
                for (const wd of weekDays) {
                  const ds = format(wd, 'yyyy-MM-dd')
                  const acts = activityMap[ds] || []
                  for (const a of acts) {
                    if (g.sport_type !== '__all__' && a.sport_type !== g.sport_type) continue
                    if (g.metric === 'distance_km') current += a.distance_km ?? 0
                    else if (g.metric === 'time_hours') current += (a.moving_time ?? 0) / 3600
                    else if (g.metric === 'activities') current += 1
                  }
                }
                const target = g.target_value as number
                const pct = target > 0 ? (current / target) * 100 : 0
                return { ...g, current_value: current, percentage: pct }
              })

            return (
              <div key={`week-${idx}`} className={clsx('col-span-7 flex items-center justify-end gap-3 px-3 py-1 rounded-lg', isLight ? 'bg-gray-50/80' : 'bg-surface-800/50')}>
                {weeklyGoalProgress.map((g: Record<string, unknown>) => {
                  const sport = g.sport_type as string
                  const color = sport === '__all__' ? '#9ca3af' : getSportColor(sport)
                  const pct = Math.min(g.percentage as number, 100)
                  return (
                    <div key={g.id as number} className="flex items-center gap-1" title={`${sport === '__all__' ? 'All' : sport}: ${(g.current_value as number).toFixed(1)} / ${g.target_value as number} ${(g.metric as string).replace('_', ' ')} (${(g.percentage as number).toFixed(0)}%)`}>
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                      <div className={clsx('w-16 h-1.5 rounded-full overflow-hidden', isLight ? 'bg-gray-200' : 'bg-surface-700')}>
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: (g.percentage as number) >= 100 ? '#22c55e' : color }} />
                      </div>
                      <span className="text-[9px] font-mono" style={{ color: (g.percentage as number) >= 100 ? '#22c55e' : '#6b7280' }}>
                        {(g.percentage as number).toFixed(0)}%
                      </span>
                    </div>
                  )
                })}
                <span className="text-[10px] text-gray-500 font-mono">
                  {totalKm.toFixed(1)} km
                </span>
                <span className="text-[10px] text-gray-500 font-mono">
                  {timeStr}
                </span>
              </div>
            )
          })() : null

          return (
            <Fragment key={dateStr}>
              {weekSummary}
              <div
                onClick={() => { setSelectedDate(dateStr); setShowModal(true) }}
                onDragOver={(e) => { e.preventDefault(); setDragOverDate(dateStr) }}
                onDragLeave={() => setDragOverDate(prev => prev === dateStr ? null : prev)}
                onDrop={(e) => {
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
                }}
                className={clsx(
                  'relative min-h-[120px] p-2 rounded-lg border transition-all duration-150',
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
                  // Compute average score for sessions on this day
                  const dayScores = daySessions
                    .map(s => sessionScores?.[String(s.id as number)])
                    .filter((sc): sc is Record<string, unknown> => sc != null && sc.overall_score != null)
                  const avgScore = dayScores.length > 0
                    ? Math.round(dayScores.reduce((sum, sc) => sum + (sc.overall_score as number), 0) / dayScores.length)
                    : null

                  return (
                    <div className="absolute top-1 right-1 flex items-center gap-1">
                      {avgScore !== null && (
                        <span
                          className="text-[9px] font-bold font-mono px-1 rounded"
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
                      onDragStart={(e) => {
                        e.stopPropagation()
                        e.dataTransfer.setData('text/plain', String(s.id))
                        e.dataTransfer.effectAllowed = 'copyMove'
                        setDraggingSessionId(s.id as number)
                        setDraggingSession(s)
                      }}
                      onDragEnd={() => { setDraggingSessionId(null); setDraggingSession(null); setDragOverDate(null) }}
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
                      onDragStart={(e) => {
                        e.stopPropagation()
                        e.dataTransfer.setData('application/race', String(r.id))
                        e.dataTransfer.effectAllowed = 'move'
                      }}
                      className={clsx(
                        'mt-0.5 text-[10px] px-1.5 py-0.5 rounded border truncate',
                        'cursor-grab active:cursor-grabbing transition-all duration-150 hover:scale-[1.02]',
                        'border-amber-500/60 text-amber-500/90 bg-amber-500/5',
                      )}
                      title={`${r.name}${r.location ? ` — ${r.location}` : ''}${r.distance_km ? ` (${r.distance_km} km)` : ''}`}
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
            </Fragment>
          )
        })}
      </div>

      {/* Weekly Report — fade in */}
      <style>{`
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes scaleIn { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }
      `}</style>
      <section>
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <div className="section-head flex-1">
            <span className="eyebrow">Weekly report</span>
          </div>
          <div className="flex items-center gap-1.5 relative">
            <ExportButton
              url={`/api/exports/weekly-report?week_start=${weekStart}`}
              label="PNG"
              filename={`weekly_report_${weekStart}.png`}
              exportType="weekly-report"
            />
            <button
              onClick={() => setWeekStart(w => format(subDays(parseISO(w), 7), 'yyyy-MM-dd'))}
              className="btn !px-3"
              aria-label="Previous week"
            >&larr;</button>
            <button
              onClick={() => setShowWeekPicker(v => !v)}
              className="btn !text-sm min-w-[140px] text-center tabular-nums"
            >
              {current?.week_start ?? weekStart}
            </button>
            <button
              onClick={() => setWeekStart(w => {
                const next = format(addDays(parseISO(w), 7), 'yyyy-MM-dd')
                return next > thisWeekStart ? thisWeekStart : next
              })}
              disabled={isCurrentWeek}
              className="btn !px-3"
              aria-label="Next week"
            >&rarr;</button>
            {showWeekPicker && (
              <WeekPicker
                currentWeekStart={weekStart}
                onSelect={setWeekStart}
                onClose={() => setShowWeekPicker(false)}
              />
            )}
          </div>
        </div>

        {weekLoading ? (
          <div className="space-y-4 animate-pulse">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className={clsx('rounded-xl p-4 h-48 border animate-pulse', isLight ? 'bg-gray-100 border-gray-200' : 'bg-surface-800 border-surface-600')} />
              <div className={clsx('rounded-xl p-4 h-48 border animate-pulse', isLight ? 'bg-gray-100 border-gray-200' : 'bg-surface-800 border-surface-600')} />
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className={clsx('rounded-xl p-4 h-24 border animate-pulse', isLight ? 'bg-gray-100 border-gray-200' : 'bg-surface-800 border-surface-600')} />
              ))}
            </div>
          </div>
        ) : current ? (
          <div className="space-y-4" style={{ animation: 'fadeIn 300ms ease-out' }}>
            {/* Activities this week + Upcoming plan side by side */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Activities this week */}
              <div className={clsx('rounded-xl p-4 border', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
                <div className="eyebrow mb-3">Activities This Week</div>
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
                          <span className={clsx('text-sm truncate flex-1', isLight ? 'text-gray-600 group-hover:text-gray-900' : 'text-gray-300 group-hover:text-gray-100')}>{a.name as string}</span>
                          <span className="text-xs text-gray-500 shrink-0">{a.sport_type as string}</span>
                          {a.distance_km != null && (
                            <span className="text-xs font-mono shrink-0" style={{ color }}>{formatDist(a.distance_km as number, a.sport_type as string)}</span>
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
                  <div className={clsx('text-sm', isLight ? 'text-gray-400' : 'text-gray-600')}>No activities yet</div>
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

            {/* Goal Progress */}
            {goalProgressData?.goals && goalProgressData.goals.length > 0 && (
              <div className={clsx('rounded-xl p-4 border', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
                <div className="eyebrow mb-3">Goal Progress</div>
                <div className="space-y-3.5">
                  {goalProgressData.goals.map((g: Record<string, unknown>) => {
                    const sport = g.sport_type as string
                    const color = sport === '__all__' ? '#9ca3af' : getSportColor(sport)
                    const pct = Math.min(g.percentage as number, 100)
                    const isComplete = (g.percentage as number) >= 100
                    const metricStr = (g.metric as string).replace('_', ' ')
                    const periodStr = g.period as string
                    return (
                      <div key={g.id as number}>
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                            <span className="text-xs text-gray-300">{sport === '__all__' ? 'All Sports' : sport}</span>
                            <span className="text-[11px] text-gray-500">{metricStr} / {periodStr}</span>
                          </div>
                          <span className="text-xs font-mono" style={{ color: isComplete ? '#22c55e' : color }}>
                            {(g.current_value as number).toFixed(1)} / {g.target_value as number} ({(g.percentage as number).toFixed(0)}%)
                          </span>
                        </div>
                        <div className={clsx('h-1.5 rounded-full overflow-hidden', isLight ? 'bg-gray-200' : 'bg-surface-700')}>
                          <div
                            className="h-full rounded-full transition-all duration-500"
                            style={{ width: `${pct}%`, backgroundColor: isComplete ? '#22c55e' : color }}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* HR Zone Distribution */}
            {current.hr_zone_distribution && Object.values(current.hr_zone_distribution).some((v: unknown) => (v as number) > 0) && (
              <div className={clsx('rounded-xl p-4 border', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
                <div className="eyebrow mb-3">HR Zone Distribution</div>
                <div className="flex gap-0.5 h-8 rounded overflow-hidden">
                  {[1, 2, 3, 4, 5].map(z => {
                    const pct = current.hr_zone_distribution?.[z] ?? 0
                    const colors = ['bg-gray-500', 'bg-blue-500', 'bg-green-500', 'bg-yellow-500', 'bg-red-500']
                    const bounds = hrZoneBounds?.[z - 1]
                    const tooltip = bounds
                      ? `Z${z}: ${pct}% (${bounds.min}–${bounds.max} bpm)`
                      : `Z${z}: ${pct}%`
                    return pct > 0 ? (
                      <div
                        key={z}
                        className={`${colors[z - 1]} flex items-center justify-center text-[10px] font-bold text-white cursor-default`}
                        style={{ width: `${pct}%`, minWidth: pct > 0 ? '4px' : 0 }}
                        title={tooltip}
                      >
                        {pct >= 8 ? `Z${z}: ${Math.round(pct)}%` : ''}
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
                  title="Distance"
                  data={current.distance_per_sport_km}
                  formatValue={(v: number, sport?: string) => formatDist(v, sport)}
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
      )}

    </div>
  )
}
