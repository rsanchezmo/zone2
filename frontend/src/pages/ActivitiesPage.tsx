import { useState, useEffect, useMemo, useLayoutEffect, useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { format, getISOWeek, startOfWeek, endOfWeek, isSameMonth } from 'date-fns'
import { useActivities, useSportTypes, useYears, useAthleteProfile, type Activity } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { distValue, getDistUnit } from '../utils/formatSpeed'
import { parseLocalDate, todayLocalStr } from '../utils/dates'
import { useTheme } from '../hooks/useTheme'
import clsx from 'clsx'
import DatePicker from '../components/shared/DatePicker'
import RouteThumbnail from '../components/shared/RouteThumbnail'

const SORT_OPTIONS = [
  { value: 'date', label: 'Date' },
  { value: 'distance', label: 'Distance' },
  { value: 'moving_time', label: 'Duration' },
  { value: 'total_elevation_gain', label: 'Elevation' },
  { value: 'average_speed', label: 'Pace/Speed' },
]

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/* ── Week grouping ─────────────────────────────────── */

interface WeekGroup {
  key: string
  label: string
  range: string
  activities: Activity[]
  totalKm: number
  totalSeconds: number
  /** The week continues on an adjacent page, so these totals cover only what's shown. */
  partial: boolean
}

/** Seconds as a week time budget, e.g. "2:08 h". */
function formatHours(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}:${m.toString().padStart(2, '0')} h`
}

/**
 * Group date-ordered activities into ISO weeks (Mon–Sun), preserving list order.
 * A page boundary can split a week across pages, so the edge groups are flagged
 * `partial` — their totals only cover the rows on this page.
 */
function groupByWeek(activities: Activity[], continuesBefore: boolean, continuesAfter: boolean): WeekGroup[] {
  const groups: WeekGroup[] = []
  const byKey = new Map<string, WeekGroup>()

  for (const a of activities) {
    if (!a.start_date_local) continue
    const date = parseLocalDate(a.start_date_local)
    const weekStart = startOfWeek(date, { weekStartsOn: 1 })
    const weekEnd = endOfWeek(date, { weekStartsOn: 1 })
    const key = format(weekStart, 'yyyy-MM-dd')

    let group = byKey.get(key)
    if (!group) {
      const end = isSameMonth(weekStart, weekEnd) ? format(weekEnd, 'd') : format(weekEnd, 'MMM d')
      group = {
        key,
        label: `Week ${getISOWeek(weekStart)}`,
        range: `${format(weekStart, 'MMM d')} – ${end}`,
        activities: [],
        totalKm: 0,
        totalSeconds: 0,
        partial: false,
      }
      byKey.set(key, group)
      groups.push(group)
    }

    group.activities.push(a)
    group.totalKm += a.distance_km ?? 0
    group.totalSeconds += a.moving_time ?? 0
  }

  if (groups.length > 0) {
    if (continuesBefore) groups[0].partial = true
    if (continuesAfter) groups[groups.length - 1].partial = true
  }

  return groups
}

/* ── Activity Card ─────────────────────────────────── */

interface ActivityCardProps {
  activity: Activity
  /** Inside a week group the header carries the range, so the card drops month and year. */
  compactDate?: boolean
}

function ActivityCard({ activity: a, compactDate }: ActivityCardProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const sportColor = getSportColor(a.sport_type)
  const distanceKm = a.distance_km
  const elevGain = a.total_elevation_gain
  const avgHR = a.average_heartrate
  const dateStr = a.start_date_local
    ? parseLocalDate(a.start_date_local).toLocaleDateString(
        undefined,
        compactDate
          ? { weekday: 'short', day: 'numeric' }
          : { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' },
      )
    : ''

  return (
    <Link
      to={`/activities/${a.id}`}
      className={clsx(
        'group flex items-center gap-3.5 rounded-xl border card-glow transition-all duration-200 p-3.5',
        isLight
          ? 'bg-white border-gray-200 hover:border-gray-300'
          : 'bg-surface-800 border-surface-600 hover:border-surface-500',
      )}
      style={{
        borderLeftWidth: 3,
        borderLeftColor: sportColor,
        '--card-accent': sportColor,
      } as React.CSSProperties}
    >
      <RouteThumbnail encodedPolyline={a.summary_polyline} color={sportColor} />

      <div className="min-w-0 flex-1">
        {/* Top row: name + sport pill + date */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className={clsx(
              'font-semibold tracking-tight truncate transition-colors',
              isLight ? 'text-gray-900 group-hover:text-gray-950' : 'text-gray-100 group-hover:text-white',
            )}>
              {a.name}
            </div>
            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
              <span
                className="inline-flex items-center gap-1 text-[10px] uppercase tracking-[0.15em] px-2 py-0.5 rounded-full border font-semibold"
                style={{
                  backgroundColor: sportColor + '15',
                  color: sportColor,
                  borderColor: `${sportColor}40`,
                }}
              >
                <span className="w-1 h-1 rounded-full" style={{ backgroundColor: sportColor }} aria-hidden="true" />
                {a.sport_type}
              </span>
              <span className={clsx('text-[11px] font-mono tabular-nums', isLight ? 'text-gray-500' : 'text-gray-500')}>{dateStr}</span>
            </div>
          </div>
          {/* Arrow indicator */}
          <svg
            className={clsx(
              'w-4 h-4 shrink-0 mt-1 transition-transform duration-200 group-hover:translate-x-0.5',
              isLight ? 'text-gray-300' : 'text-gray-600',
            )}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>

        {/* Stats row */}
        <div className="flex items-center gap-4 mt-3 flex-wrap tabular-nums">
          {distanceKm != null && (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
              <span className={clsx('text-sm font-mono font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>
                {distValue(distanceKm, a.sport_type)}
              </span>
              <span className="text-[10px] text-gray-500 uppercase tracking-wider">{getDistUnit(a.sport_type)}</span>
            </div>
          )}
          {!!a.moving_time_formatted && (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <circle cx="12" cy="12" r="10" /><path strokeLinecap="round" d="M12 6v6l4 2" />
              </svg>
              <span className={clsx('text-sm font-mono font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>{String(a.moving_time_formatted)}</span>
            </div>
          )}
          {!!a.formatted_pace && (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              <span className={clsx('text-sm font-mono font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>{String(a.formatted_pace)}</span>
            </div>
          )}
          {elevGain != null && elevGain > 0 && (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 17l6-6 4 4 8-8" />
              </svg>
              <span className={clsx('text-sm font-mono font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>{Math.round(elevGain)}</span>
              <span className="text-[10px] text-gray-500 uppercase tracking-wider">m</span>
            </div>
          )}
          {avgHR != null && (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-red-400/60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
              </svg>
              <span className={clsx('text-sm font-mono font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>{Math.round(avgHR)}</span>
              <span className="text-[10px] text-gray-500 uppercase tracking-wider">bpm</span>
            </div>
          )}
        </div>
      </div>
    </Link>
  )
}

/* ── Activities Page ───────────────────────────────── */
export default function ActivitiesPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [searchParams, setSearchParams] = useSearchParams()

  // Initialize state from URL params (preserves state on back navigation)
  const [page, setPage] = useState(() => Number(searchParams.get('page')) || 1)
  const [sportType, setSportType] = useState<string>(() => searchParams.get('sport') || '')
  const [year, setYear] = useState<number | undefined>(() => {
    const y = searchParams.get('year')
    return y ? Number(y) : undefined
  })
  const [searchInput, setSearchInput] = useState(() => searchParams.get('q') || '')
  const [todayStr] = useState(() => todayLocalStr())
  const [dateFrom, setDateFrom] = useState(() => searchParams.get('from') || '')
  const [dateTo, setDateTo] = useState(() => searchParams.get('to') || todayStr)
  const [sortBy, setSortBy] = useState(() => searchParams.get('sort') || 'date')
  const [sortDir, setSortDir] = useState<'desc' | 'asc'>(() => (searchParams.get('dir') === 'asc' ? 'asc' : 'desc'))
  const [gearId, setGearId] = useState<string>(() => searchParams.get('gear_id') || '')

  // Sync state to URL params (replaces history entry so back button works)
  useEffect(() => {
    const params = new URLSearchParams()
    if (page > 1) params.set('page', String(page))
    if (sportType) params.set('sport', sportType)
    if (year) params.set('year', String(year))
    if (searchInput) params.set('q', searchInput)
    if (dateFrom) params.set('from', dateFrom)
    if (dateTo && dateTo !== todayStr) params.set('to', dateTo)
    if (sortBy !== 'date') params.set('sort', sortBy)
    if (sortDir !== 'desc') params.set('dir', sortDir)
    if (gearId) params.set('gear_id', gearId)
    setSearchParams(params, { replace: true })
  }, [page, sportType, year, searchInput, dateFrom, dateTo, todayStr, sortBy, sortDir, gearId, setSearchParams])

  // Save scroll position before navigating away, restore on mount
  useEffect(() => {
    const saveScroll = () => sessionStorage.setItem('activities-scroll', String(window.scrollY))
    window.addEventListener('beforeunload', saveScroll)
    return () => {
      saveScroll()
      window.removeEventListener('beforeunload', saveScroll)
    }
  }, [])

  const debouncedSearch = useDebounce(searchInput, 300)

  const { data: sportTypes } = useSportTypes()
  const { data: years } = useYears()

  // The default "From" (Jan 1 of the earliest activity year) excludes nothing,
  // so it's display-only: only an explicitly chosen date is sent to the query.
  // This keeps the initial mount to a single request.
  const defaultDateFrom = years && years.length > 0 ? `${years[years.length - 1]}-01-01` : ''

  const { data, isLoading, isFetching } = useActivities(
    page, 20,
    sportType || undefined,
    year,
    debouncedSearch || undefined,
    dateFrom || undefined,
    dateTo || undefined,
    sortBy,
    sortDir,
    gearId || undefined,
  )

  // Restore the saved scroll offset exactly once per mount (once the list has
  // rendered), then drop the key so later filter/page changes don't re-jump.
  const scrollRestored = useRef(false)
  useLayoutEffect(() => {
    if (scrollRestored.current || !data) return
    scrollRestored.current = true
    const saved = sessionStorage.getItem('activities-scroll')
    if (!saved) return
    sessionStorage.removeItem('activities-scroll')
    requestAnimationFrame(() => window.scrollTo(0, Number(saved)))
  }, [data])

  const totalPages = data ? Math.ceil(data.total / data.per_page) : 0

  const dateRangeChanged =
    (dateFrom !== '' && dateFrom !== defaultDateFrom) || (dateTo !== '' && dateTo !== todayStr)

  const activeFilterCount = [
    sportType,
    year,
    debouncedSearch,
    sortBy !== 'date' || sortDir !== 'desc' ? 'sort' : '',
    gearId,
    dateRangeChanged ? 'dates' : '',
  ].filter(Boolean).length

  const clearAll = () => {
    setSportType('')
    setYear(undefined)
    setSearchInput('')
    setDateFrom('')
    setDateTo(todayStr)
    setSortBy('date')
    setSortDir('desc')
    setGearId('')
    setPage(1)
  }

  // Resolve gear_id → name for the active-filter chip
  const { data: profileForGear } = useAthleteProfile()
  const gearName = useMemo(() => {
    if (!gearId || !profileForGear) return null
    const shoes = profileForGear.shoes ?? []
    const bikes = profileForGear.bikes ?? []
    const found = [...shoes, ...bikes].find(g => g.id === gearId)
    if (!found) return gearId
    const nick = found.nickname?.trim()
    return nick || found.name || gearId
  }, [gearId, profileForGear])

  // Week grouping only holds under a date sort — any other order interleaves
  // weeks, so those sorts keep the flat list.
  const weekGroups = useMemo(() => {
    if (sortBy !== 'date' || !data?.items?.length) return null
    const lastPage = Math.ceil(data.total / data.per_page)
    return groupByWeek(data.items, data.page > 1, data.page < lastPage)
  }, [sortBy, data])

  // Page range for pagination
  const pageRange = useMemo(() => {
    const range: number[] = []
    const delta = 2
    const start = Math.max(1, page - delta)
    const end = Math.min(totalPages, page + delta)
    for (let i = start; i <= end; i++) range.push(i)
    return range
  }, [page, totalPages])

  const selectClass = 'select'

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      {/* ── Breadcrumb header ─────────────────────────── */}
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="eyebrow">Activities</span>
          <span className={clsx('text-[11px]', isLight ? 'text-gray-300' : 'text-gray-700')}>·</span>
          {!isLoading && data ? (
            <span className={clsx('text-[11px] font-mono tabular-nums', isLight ? 'text-gray-500' : 'text-gray-500')}>
              {data.total.toLocaleString()} activit{data.total === 1 ? 'y' : 'ies'}
              {debouncedSearch && <> matching &ldquo;<span className={isLight ? 'text-gray-700' : 'text-gray-300'}>{debouncedSearch}</span>&rdquo;</>}
            </span>
          ) : (
            <span className="text-[11px] text-gray-500 normal-case tracking-normal">every workout you've logged</span>
          )}
        </div>
        {activeFilterCount > 0 && (
          <button
            onClick={clearAll}
            className="btn"
          >
            Clear {activeFilterCount} filter{activeFilterCount > 1 ? 's' : ''}
          </button>
        )}
      </header>

      {/* ── Active gear filter chip ─────────────────── */}
      {gearId && (
        <div
          className={clsx(
            'inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-[11px] uppercase tracking-[0.15em]',
            isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-800 border-surface-600 text-gray-300',
          )}
        >
          <span className={isLight ? 'text-gray-400' : 'text-gray-500'}>Gear</span>
          <span className={isLight ? 'text-gray-900' : 'text-gray-100'}>{gearName ?? gearId}</span>
          <button
            onClick={() => {
              setGearId('')
              setPage(1)
            }}
            aria-label="Clear gear filter"
            className={clsx('ml-1', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-500 hover:text-gray-200')}
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {/* ── Filter toolbar ─────────────────────────── */}
      <section className={clsx(
        'panel p-3 space-y-2.5',
        isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
      )}>
        {/* Row 1: Search */}
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M11 19a8 8 0 100-16 8 8 0 000 16z" />
          </svg>
          <input
            type="text"
            placeholder="Search by activity name..."
            value={searchInput}
            onChange={e => {
              setSearchInput(e.target.value)
              setPage(1)
            }}
            className="input w-full !pl-9 !pr-3"
          />
          {searchInput && (
            <button
              onClick={() => {
                setSearchInput('')
                setPage(1)
              }}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        {/* Row 2: Filters */}
        <div className="flex flex-wrap items-center gap-2">
          <DatePicker value={dateFrom || defaultDateFrom} onChange={v => {
            setDateFrom(v)
            setPage(1)
          }} label="From" />
          <DatePicker value={dateTo} onChange={v => {
            setDateTo(v)
            setPage(1)
          }} label="To" />

          <div className="w-px h-6 bg-surface-600 mx-1 hidden sm:block" />

          <select
            value={sportType}
            onChange={e => {
              setSportType(e.target.value)
              setPage(1)
            }}
            className={selectClass}
          >
            <option value="">All Sports</option>
            {(sportTypes ?? []).map((s: string) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>

          <select
            value={year ?? ''}
            onChange={e => {
              setYear(e.target.value ? Number(e.target.value) : undefined)
              setPage(1)
            }}
            className={selectClass}
          >
            <option value="">All Years</option>
            {(years ?? []).map((y: number) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>

          <div className="w-px h-6 bg-surface-600 mx-1 hidden sm:block" />

          {/* Sort controls */}
          <div className="flex items-center gap-1.5">
            <span className="eyebrow text-[9px] shrink-0">Sort</span>
            <select
              value={sortBy}
              onChange={e => {
                setSortBy(e.target.value)
                setPage(1)
              }}
              className={selectClass}
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <button
              onClick={() => {
                setSortDir(d => d === 'desc' ? 'asc' : 'desc')
                setPage(1)
              }}
              className="btn flex items-center justify-center !px-2"
              title={sortDir === 'desc' ? 'Descending — click for ascending' : 'Ascending — click for descending'}
              aria-label={sortDir === 'desc' ? 'Sort ascending' : 'Sort descending'}
            >
              <svg className={clsx('w-4 h-4 transition-transform duration-200', sortDir === 'asc' && 'rotate-180')} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          </div>
        </div>
      </section>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div
              key={i}
              className={clsx(
                'panel p-4 animate-pulse',
                isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
              )}
            >
              <div className={clsx('h-4 rounded w-1/3 mb-3', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
              <div className={clsx('h-3 rounded w-1/4', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
            </div>
          ))}
        </div>
      ) : data?.items?.length === 0 ? (
        <div className={clsx(
          'panel p-10 flex flex-col items-center justify-center gap-3 text-center',
          isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
        )}>
          <svg className={clsx('w-9 h-9', isLight ? 'text-gray-300' : 'text-gray-600')} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <p className={clsx('text-sm', isLight ? 'text-gray-500' : 'text-gray-500')}>No activities found</p>
          <p className={clsx('text-[11px]', isLight ? 'text-gray-400' : 'text-gray-600')}>Try adjusting your filters</p>
        </div>
      ) : (
        <>
          <div className={clsx('transition-opacity duration-200', isFetching && !isLoading && 'opacity-60')}>
            {weekGroups ? (
              <div className="space-y-6">
                {weekGroups.map(group => (
                  <section key={group.key} className="space-y-2.5">
                    <div className="sticky top-0 z-10 flex flex-wrap items-center gap-x-3 gap-y-0.5 py-2 bg-surface-900/85 backdrop-blur-sm">
                      <span className="eyebrow shrink-0">{group.label} · {group.range}</span>
                      <div
                        className="hidden sm:block flex-1 h-px"
                        style={{ background: 'linear-gradient(to right, var(--color-surface-600) 0%, transparent 75%)' }}
                      />
                      <span
                        className="shrink-0 text-[11px] text-gray-500 font-mono tabular-nums"
                        title={group.partial ? 'This week continues on an adjacent page — totals cover the shown activities only' : undefined}
                      >
                        {group.activities.length} {group.activities.length === 1 ? 'activity' : 'activities'}
                        {group.totalKm > 0 && (
                          <> · <span className={isLight ? 'text-gray-900' : 'text-gray-100'}>{group.totalKm.toFixed(1)} km</span></>
                        )}
                        {group.totalSeconds > 0 && <> · {formatHours(group.totalSeconds)}</>}
                        {group.partial && <span className={isLight ? 'text-gray-400' : 'text-gray-600'}> · shown</span>}
                      </span>
                    </div>
                    <div className="space-y-2 stagger-children">
                      {group.activities.map(a => (
                        <ActivityCard key={a.id} activity={a} compactDate />
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            ) : (
              <div className="space-y-2 stagger-children">
                {data?.items?.map(a => (
                  <ActivityCard key={a.id} activity={a} />
                ))}
              </div>
            )}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-1 pt-2 pb-4">
              <button
                onClick={() => setPage(1)}
                disabled={page === 1}
                className={clsx(
                  'px-2 py-1 rounded text-xs transition-colors disabled:opacity-20',
                  isLight ? 'hover:bg-gray-100 text-gray-500' : 'hover:bg-surface-700 text-gray-500',
                )}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                </svg>
              </button>
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className={clsx(
                  'px-2 py-1 rounded text-xs transition-colors disabled:opacity-20',
                  isLight ? 'hover:bg-gray-100 text-gray-500' : 'hover:bg-surface-700 text-gray-500',
                )}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              {pageRange[0] > 1 && (
                <span className="text-xs text-gray-600 px-1">&hellip;</span>
              )}
              {pageRange.map(p => (
                <button
                  key={p}
                  onClick={() => setPage(p)}
                  className={clsx(
                    'w-8 h-8 rounded text-sm font-mono tabular-nums transition-colors',
                    p === page
                      ? isLight
                        ? 'bg-gray-900 text-white font-semibold'
                        : 'bg-white/10 text-white font-semibold'
                      : isLight
                        ? 'text-gray-500 hover:bg-gray-100'
                        : 'text-gray-500 hover:bg-surface-700',
                  )}
                  aria-label={`Page ${p}`}
                  aria-current={p === page ? 'page' : undefined}
                >
                  {p}
                </button>
              ))}
              {pageRange[pageRange.length - 1] < totalPages && (
                <span className="text-xs text-gray-600 px-1">&hellip;</span>
              )}
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className={clsx(
                  'px-2 py-1 rounded text-xs transition-colors disabled:opacity-20',
                  isLight ? 'hover:bg-gray-100 text-gray-500' : 'hover:bg-surface-700 text-gray-500',
                )}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </button>
              <button
                onClick={() => setPage(totalPages)}
                disabled={page === totalPages}
                className={clsx(
                  'px-2 py-1 rounded text-xs transition-colors disabled:opacity-20',
                  isLight ? 'hover:bg-gray-100 text-gray-500' : 'hover:bg-surface-700 text-gray-500',
                )}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                </svg>
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
