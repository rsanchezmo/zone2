import {
  useState, useMemo, useEffect, useCallback, lazy, Suspense, type DragEvent as ReactDragEvent,
} from 'react'
import {
  startOfMonth, endOfMonth, eachDayOfInterval, format, addMonths, subMonths, addDays, subDays,
  isSameMonth, startOfWeek, endOfWeek, parseISO,
} from 'date-fns'
import clsx from 'clsx'
import {
  useActivitiesByDateRange, useCalendarSessionsByRange, useCreateSession, useUpdateSession,
  useDeleteSession, useWeeklyReport, useAthleteZones, useStreaks, useGoalProgress, useGoals,
  useSessionScores, usePlanAccomplishment, useRaceEventsByRange, useUpcomingRaces,
  useCreateRaceEvent, useUpdateRaceEvent, useDeleteRaceEvent, useActivities, type Activity,
  type RaceEvent, type TrainingSession,
} from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { localDateStr, parseLocalDate } from '../utils/dates'
import { useTheme } from '../hooks/useTheme'
import { useToast } from '../hooks/useToast'
import {
  buildWeekSummaries, formatWeekRange, type CalendarGridProps, type DayDropProps, type WeekRow,
} from '../components/calendar/calendar'
import { MonthPicker, WeekPicker } from '../components/calendar/CalendarPickers'
import CalendarBadges from '../components/calendar/CalendarBadges'
import RaceCountdown from '../components/calendar/RaceCountdown'
import MonthGrid from '../components/calendar/MonthGrid'
import WeekView from '../components/calendar/WeekView'
import WeekInspector from '../components/calendar/WeekInspector'

// Recharts and the day editor load on demand: the calendar paints without them
const WeekDetailCharts = lazy(() => import('../components/calendar/WeekDetailCharts'))
const SessionModal = lazy(() => import('../components/calendar/SessionModal'))

type CalendarView = 'month' | 'week'

const VIEW_STORAGE_KEY = 'calendar-view'

/** Week view is the only legible default on a phone — below md the month grid
 *  collapses to dots, which can't carry a session's name or its targets. */
function getInitialView(): CalendarView {
  const stored = localStorage.getItem(VIEW_STORAGE_KEY)
  if (stored === 'month' || stored === 'week') return stored
  return window.matchMedia('(max-width: 767px)').matches ? 'week' : 'month'
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
  const { data: newestActivity, isFetched: newestFetched } = useActivities(1, 1)
  const latestActiveWeek = useMemo(() => {
    const newest = newestActivity?.items?.[0]?.start_date_local
    if (!newest) return null
    return format(startOfWeek(parseLocalDate(newest), { weekStartsOn: 1 }), 'yyyy-MM-dd')
  }, [newestActivity])

  const [pickedWeek, setPickedWeek] = useState<string | null>(null)
  const weekStart = pickedWeek ?? latestActiveWeek ?? thisWeekStart
  // Queries on the inspected week wait for the newest activity, which picks the
  // default week: starting on this one and then moving would fetch them all twice.
  const weekKnown = pickedWeek !== null || newestFetched

  const [sportFilter, setSportFilter] = useState<Set<string>>(new Set())
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)
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
  }, [currentMonth, weekStart])

  // The week view's grid is the inspected week, so it waits for it too
  const gridFrom = view === 'week' && !weekKnown ? undefined : dateFrom
  const { data: activitiesData, isLoading: activitiesLoading } = useActivitiesByDateRange(gridFrom, dateTo)
  // Fetch the full grid range so sessions on leading/trailing days of adjacent months render too
  const { data: sessions } = useCalendarSessionsByRange(gridFrom, dateTo)
  const { data: sessionScores } = useSessionScores(gridFrom, dateTo)
  const createSession = useCreateSession()
  const updateSession = useUpdateSession()
  const deleteSession = useDeleteSession()
  const { data: raceEventsRange } = useRaceEventsByRange(gridFrom, dateTo)
  const { data: upcomingRaces } = useUpcomingRaces()
  const createRace = useCreateRaceEvent()
  const updateRace = useUpdateRaceEvent()
  const deleteRace = useDeleteRaceEvent()

  // Weekly report — in week view the grid's own selector drives `weekStart`,
  // so the report always describes the week on screen.
  const isCurrentWeek = weekStart === thisWeekStart
  const inspectedWeek = weekKnown ? weekStart : undefined
  const { data: weekData, isLoading: weekQueryLoading } = useWeeklyReport(inspectedWeek)
  const weekLoading = weekQueryLoading || !weekKnown
  const { data: athleteZones } = useAthleteZones()
  const hrZoneBounds = athleteZones?.heart_rate?.zones ?? undefined
  const current = weekData?.current
  const previous = weekData?.previous

  // weekStart is always a Monday (the backend snaps to Monday too), so the range is known
  // locally and these queries can fire in parallel with the weekly report
  const weekEndStr = format(addDays(parseISO(weekStart), 6), 'yyyy-MM-dd')
  const { data: goalProgressData } = useGoalProgress(inspectedWeek)
  // The week's activities and planned sessions come from the grid while it shows
  // the week, and from their own queries once the month moves off it.
  const weekInGrid = weekStart >= dateFrom && weekEndStr <= dateTo
  const ownWeekFrom = weekInGrid ? undefined : inspectedWeek
  const { data: ownWeekActivities } = useActivitiesByDateRange(ownWeekFrom, weekEndStr)
  const { data: ownWeekPlanned } = useCalendarSessionsByRange(ownWeekFrom, weekEndStr)
  const weekActivities = useMemo(() => {
    if (!weekInGrid) return ownWeekActivities?.items
    return activitiesData?.items.filter(a => {
      const day = a.start_date_local ? localDateStr(a.start_date_local) : null
      return day !== null && day >= weekStart && day <= weekEndStr
    })
  }, [weekInGrid, ownWeekActivities, activitiesData, weekStart, weekEndStr])
  const weekPlanned = useMemo(
    () => (weekInGrid ? sessions?.filter(s => s.date >= weekStart && s.date <= weekEndStr) : ownWeekPlanned),
    [weekInGrid, sessions, ownWeekPlanned, weekStart, weekEndStr],
  )

  const todayStr = format(new Date(), 'yyyy-MM-dd')

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

  // Memoized so km/time totals and goal bars don't recompute on every dragOver re-render
  const weekSummaries = useMemo(
    () => buildWeekSummaries(days, activityMap, sessionMap, calGoals, showSport),
    [days, activityMap, sessionMap, calGoals, showSport],
  )

  /** The month grid as one block per week, each carrying its own totals. */
  const weekRows = useMemo(() => {
    const rows: WeekRow[] = []
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

  const gridProps: CalendarGridProps = {
    activityMap, sessionMap, raceMap, scores: sessionScores, dragOverDate, draggingSessionId,
    dayDropProps, onOpenDay: openDay, onSessionDragStart: handleSessionDragStart,
    onSessionDragEnd: handleSessionDragEnd, onRaceDragStart: handleRaceDragStart,
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
                  <MonthPicker current={currentMonth} onSelect={setCurrentMonth} />
                  <button onClick={() => setCurrentMonth(m => addMonths(m, 1))} className="btn !px-3" aria-label="Next month">&rarr;</button>
                </>
              ) : (
                <>
                  <button
                    onClick={() => setPickedWeek(format(subDays(parseISO(weekStart), 7), 'yyyy-MM-dd'))}
                    className="btn !px-3"
                    aria-label="Previous week"
                  >&larr;</button>
                  <WeekPicker currentWeekStart={weekStart} onSelect={setPickedWeek} />
                  {/* Unclamped, unlike the report's own picker in month view — the
                      point of week view is reading a plan that lives in the future. */}
                  <button
                    onClick={() => setPickedWeek(format(addDays(parseISO(weekStart), 7), 'yyyy-MM-dd'))}
                    className="btn !px-3"
                    aria-label="Next week"
                  >&rarr;</button>
                </>
              )}
            </div>
          </div>
        </div>
        <CalendarBadges streaks={streakData} planRate={planRate} />
        <RaceCountdown races={upcomingRaces} />
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
            <WeekView days={days} summary={weekSummaries[0]} {...gridProps} />
          ) : (
            <MonthGrid
              key={format(currentMonth, 'yyyy-MM')}
              currentMonth={currentMonth}
              weekRows={weekRows}
              selectedWeek={weekStart}
              loading={activitiesLoading}
              onPickWeek={setPickedWeek}
              {...gridProps}
            />
          )}
        </div>

        <WeekInspector
          weekStart={weekStart}
          report={current}
          loading={weekLoading}
          activities={weekActivities}
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
          onAddRace={race => createRace.mutate(race)}
          onUpdateRace={(id, race) => updateRace.mutate({ id, ...race })}
          onDeleteRace={(id) => deleteRace.mutate(id)}
          onClose={() => setShowModal(false)}
        />
        </Suspense>
      )}

    </div>
  )
}
