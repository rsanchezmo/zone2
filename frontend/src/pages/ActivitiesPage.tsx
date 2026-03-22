import { useState, useEffect, useRef, useCallback, useMemo, useLayoutEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useActivities, useSportTypes, useYears } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { getSportCategory } from '../utils/formatSpeed'
import { useTheme } from '../hooks/useTheme'
import clsx from 'clsx'
import {
  startOfMonth, endOfMonth, eachDayOfInterval, format, addMonths, subMonths,
  startOfWeek, endOfWeek, isSameMonth, isToday, parse, isValid,
} from 'date-fns'

const SORT_OPTIONS = [
  { value: 'date', label: 'Date' },
  { value: 'distance', label: 'Distance' },
  { value: 'moving_time', label: 'Duration' },
  { value: 'total_elevation_gain', label: 'Elevation' },
  { value: 'average_speed', label: 'Pace/Speed' },
]

const WEEKDAY_HEADERS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/** Format a yyyy-MM-dd string to dd/MM/yyyy for display */
function toDisplay(isoDate: string): string {
  if (!isoDate) return ''
  const [y, m, d] = isoDate.split('-')
  return `${d}/${m}/${y}`
}

/** Parse dd/MM/yyyy input to yyyy-MM-dd, returns '' if invalid */
function fromDisplay(display: string): string {
  if (!display) return ''
  const cleaned = display.replace(/[^\d/]/g, '')
  const parts = cleaned.split('/')
  if (parts.length !== 3) return ''
  const [d, m, y] = parts
  if (!d || !m || !y || y.length !== 4) return ''
  const date = parse(`${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`, 'yyyy-MM-dd', new Date())
  if (!isValid(date)) return ''
  return format(date, 'yyyy-MM-dd')
}

/* ── DatePicker (Calendar Page style) ──────────────── */
function DatePicker({ value, onChange, label }: {
  value: string  // yyyy-MM-dd or ''
  onChange: (v: string) => void
  label: string
}) {
  const [open, setOpen] = useState(false)
  const [viewMonth, setViewMonth] = useState(() =>
    value ? new Date(value + 'T00:00:00') : new Date()
  )
  const [textInput, setTextInput] = useState(() => toDisplay(value))
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setTextInput(toDisplay(value))
  }, [value])

  useEffect(() => {
    if (value) {
      setViewMonth(new Date(value + 'T00:00:00'))
    }
  }, [value])

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const handleTextChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    setTextInput(raw)
    if (raw.length === 10) {
      const iso = fromDisplay(raw)
      if (iso) onChange(iso)
    }
  }, [onChange])

  const handleTextBlur = useCallback(() => {
    if (!textInput) {
      onChange('')
      return
    }
    const iso = fromDisplay(textInput)
    if (iso) {
      onChange(iso)
    } else {
      setTextInput(toDisplay(value))
    }
  }, [textInput, value, onChange])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      (e.target as HTMLInputElement).blur()
    }
  }, [])

  const selectDay = useCallback((d: Date) => {
    onChange(format(d, 'yyyy-MM-dd'))
    setOpen(false)
  }, [onChange])

  const monthStart = startOfMonth(viewMonth)
  const monthEnd = endOfMonth(viewMonth)
  const calStart = startOfWeek(monthStart, { weekStartsOn: 1 })
  const calEnd = endOfWeek(monthEnd, { weekStartsOn: 1 })
  const days = eachDayOfInterval({ start: calStart, end: calEnd })
  const selectedIso = value

  return (
    <div ref={ref} className="relative">
      <div className="flex items-center gap-1">
        <span className="text-[11px] text-gray-500 shrink-0">{label}</span>
        <input
          type="text"
          placeholder="dd/mm/yyyy"
          value={textInput}
          onChange={handleTextChange}
          onBlur={handleTextBlur}
          onKeyDown={handleKeyDown}
          onFocus={() => setOpen(true)}
          className="input w-[110px] font-mono"
          maxLength={10}
        />
        <button
          onClick={() => setOpen(o => !o)}
          className="btn !p-1.5"
          type="button"
        >
          <svg className="w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
        </button>
      </div>

      {open && (
        <div className="absolute top-full mt-1 z-50 bg-surface-800 border border-surface-600 rounded-xl p-3 shadow-xl w-[250px]">
          {/* Year nav */}
          <div className="flex items-center justify-between mb-1">
            <button onClick={() => setViewMonth(m => new Date(m.getFullYear() - 1, m.getMonth(), 1))} className="text-gray-500 hover:text-gray-100 px-1 text-[11px]">&larr;</button>
            <span className="text-[11px] text-gray-500">{viewMonth.getFullYear()}</span>
            <button onClick={() => setViewMonth(m => new Date(m.getFullYear() + 1, m.getMonth(), 1))} className="text-gray-500 hover:text-gray-100 px-1 text-[11px]">&rarr;</button>
          </div>
          {/* Month nav */}
          <div className="flex items-center justify-between mb-2">
            <button onClick={() => setViewMonth(m => subMonths(m, 1))} className="text-gray-400 hover:text-gray-100 px-1 text-sm">&larr;</button>
            <span className="text-xs font-medium text-gray-300">{format(viewMonth, 'MMMM')}</span>
            <button onClick={() => setViewMonth(m => addMonths(m, 1))} className="text-gray-400 hover:text-gray-100 px-1 text-sm">&rarr;</button>
          </div>

          {/* Weekday headers */}
          <div className="grid grid-cols-7 gap-0.5 text-center mb-1">
            {WEEKDAY_HEADERS.map(d => (
              <div key={d} className="text-[9px] text-gray-600 py-0.5">{d}</div>
            ))}
          </div>

          {/* Day grid */}
          <div className="grid grid-cols-7 gap-0.5 text-center">
            {days.map(d => {
              const ds = format(d, 'yyyy-MM-dd')
              const inMonth = isSameMonth(d, viewMonth)
              const isSelected = ds === selectedIso
              const isTodayDate = isToday(d)
              return (
                <button
                  key={ds}
                  onClick={() => selectDay(d)}
                  className={clsx(
                    'text-[11px] py-1 rounded transition-colors',
                    !inMonth && 'text-gray-700',
                    inMonth && !isSelected && !isTodayDate && 'text-gray-400 hover:bg-surface-700',
                    isTodayDate && !isSelected && 'bg-surface-600 text-gray-300',
                    isSelected && 'bg-gray-400/20 text-gray-100 font-bold',
                  )}
                >
                  {format(d, 'd')}
                </button>
              )
            })}
          </div>

          {/* Quick actions */}
          <div className="flex gap-1 mt-2">
            <button
              onClick={() => { selectDay(new Date()) }}
              className="flex-1 text-[11px] text-gray-400 hover:text-gray-100 py-1 bg-surface-700 rounded"
            >
              Today
            </button>
            {value && (
              <button
                onClick={() => { onChange(''); setOpen(false) }}
                className="flex-1 text-[11px] text-gray-400 hover:text-gray-100 py-1 bg-surface-700 rounded"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Activity Card ─────────────────────────────────── */
function ActivityCard({ activity: a }: { activity: Record<string, unknown> }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const sportColor = getSportColor(a.sport_type as string)
  const distanceKm = a.distance_km as number | undefined
  const elevGain = a.total_elevation_gain as number | undefined
  const avgHR = a.average_heartrate as number | undefined
  const dateStr = a.start_date_local
    ? new Date(a.start_date_local as string).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
    : ''

  return (
    <Link
      to={`/activities/${a.id}`}
      className={clsx(
        'group block rounded-xl border card-glow transition-all duration-200',
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
      <div className="p-4">
        {/* Top row: name + date */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className={clsx(
              'font-medium truncate group-hover:text-white transition-colors',
              isLight && 'group-hover:text-gray-900',
            )}>
              {a.name as string}
            </div>
            <div className="flex items-center gap-1.5 mt-1">
              <span
                className="text-[11px] font-medium px-1.5 py-0.5 rounded-full"
                style={{
                  backgroundColor: sportColor + '18',
                  color: sportColor,
                }}
              >
                {a.sport_type as string}
              </span>
              <span className="text-[11px] text-gray-500">{dateStr}</span>
            </div>
          </div>
          {/* Arrow indicator */}
          <svg
            className={clsx(
              'w-4 h-4 shrink-0 mt-1 transition-transform duration-200 group-hover:translate-x-0.5',
              isLight ? 'text-gray-300' : 'text-gray-600',
            )}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>

        {/* Stats row */}
        <div className="flex items-center gap-4 mt-3">
          {distanceKm != null && (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
              <span className="text-sm font-mono font-medium">{getSportCategory(a.sport_type as string) === 'swimming' ? Math.round((distanceKm ?? 0) * 1000) : distanceKm}</span>
              <span className="text-[11px] text-gray-500">{getSportCategory(a.sport_type as string) === 'swimming' ? 'm' : 'km'}</span>
            </div>
          )}
          {!!a.moving_time_formatted && (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <circle cx="12" cy="12" r="10" /><path strokeLinecap="round" d="M12 6v6l4 2" />
              </svg>
              <span className="text-sm font-mono font-medium">{String(a.moving_time_formatted)}</span>
            </div>
          )}
          {!!a.formatted_pace && (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              <span className="text-sm font-mono font-medium">{String(a.formatted_pace)}</span>
            </div>
          )}
          {elevGain != null && elevGain > 0 && (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 17l6-6 4 4 8-8" />
              </svg>
              <span className="text-sm font-mono font-medium">{Math.round(elevGain)}</span>
              <span className="text-[11px] text-gray-500">m</span>
            </div>
          )}
          {avgHR != null && (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-red-400/60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
              </svg>
              <span className="text-sm font-mono font-medium">{Math.round(avgHR)}</span>
              <span className="text-[11px] text-gray-500">bpm</span>
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
  const [dateFrom, setDateFrom] = useState(() => searchParams.get('from') || '')
  const [dateTo, setDateTo] = useState(() => searchParams.get('to') || format(new Date(), 'yyyy-MM-dd'))
  const [sortBy, setSortBy] = useState(() => searchParams.get('sort') || 'date')
  const [sortDir, setSortDir] = useState<'desc' | 'asc'>(() => (searchParams.get('dir') === 'asc' ? 'asc' : 'desc'))
  const [defaultsApplied, setDefaultsApplied] = useState(() => !!searchParams.get('from'))

  // Sync state to URL params (replaces history entry so back button works)
  useEffect(() => {
    const params = new URLSearchParams()
    if (page > 1) params.set('page', String(page))
    if (sportType) params.set('sport', sportType)
    if (year) params.set('year', String(year))
    if (searchInput) params.set('q', searchInput)
    if (dateFrom) params.set('from', dateFrom)
    if (dateTo && dateTo !== format(new Date(), 'yyyy-MM-dd')) params.set('to', dateTo)
    if (sortBy !== 'date') params.set('sort', sortBy)
    if (sortDir !== 'desc') params.set('dir', sortDir)
    setSearchParams(params, { replace: true })
  }, [page, sportType, year, searchInput, dateFrom, dateTo, sortBy, sortDir, setSearchParams])

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

  // Default "from" to earliest activity date (Jan 1 of earliest year)
  useEffect(() => {
    if (!defaultsApplied && years && years.length > 0) {
      const earliestYear = years[years.length - 1]
      setDateFrom(`${earliestYear}-01-01`)
      setDefaultsApplied(true)
    }
  }, [years, defaultsApplied])

  const { data, isLoading, isFetching } = useActivities(
    page, 20,
    sportType || undefined,
    year,
    debouncedSearch || undefined,
    dateFrom || undefined,
    dateTo || undefined,
    sortBy,
    sortDir,
  )

  useLayoutEffect(() => {
    const saved = sessionStorage.getItem('activities-scroll')
    if (saved) {
      requestAnimationFrame(() => window.scrollTo(0, Number(saved)))
    }
  }, [data])

  const totalPages = data ? Math.ceil(data.total / data.per_page) : 0

  // Reset page when any filter changes
  const prevFilters = useRef({ sportType, year, debouncedSearch, dateFrom, dateTo, sortBy, sortDir })
  useEffect(() => {
    const prev = prevFilters.current
    if (
      prev.sportType !== sportType || prev.year !== year ||
      prev.debouncedSearch !== debouncedSearch || prev.dateFrom !== dateFrom ||
      prev.dateTo !== dateTo || prev.sortBy !== sortBy || prev.sortDir !== sortDir
    ) {
      setPage(1)
      prevFilters.current = { sportType, year, debouncedSearch, dateFrom, dateTo, sortBy, sortDir }
    }
  }, [sportType, year, debouncedSearch, dateFrom, dateTo, sortBy, sortDir])

  const activeFilterCount = [
    sportType,
    year,
    debouncedSearch,
    sortBy !== 'date' || sortDir !== 'desc' ? 'sort' : '',
  ].filter(Boolean).length

  const clearAll = () => {
    setSportType('')
    setYear(undefined)
    setSearchInput('')
    setDateFrom('')
    setDateTo('')
    setSortBy('date')
    setSortDir('desc')
    setPage(1)
  }

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
    <div className="max-w-6xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="page-title">Activities</h2>
          {!isLoading && data && (
            <p className="text-sm text-gray-500 mt-0.5">
              {data.total.toLocaleString()} activit{data.total === 1 ? 'y' : 'ies'}
              {debouncedSearch && <> matching &ldquo;<span className="text-gray-400">{debouncedSearch}</span>&rdquo;</>}
            </p>
          )}
        </div>
        {activeFilterCount > 0 && (
          <button
            onClick={clearAll}
            className={clsx(
              'text-xs px-2.5 py-1 rounded-full border transition-colors',
              isLight
                ? 'text-gray-500 border-gray-200 hover:bg-gray-50 hover:text-gray-700'
                : 'text-gray-400 border-surface-600 hover:bg-surface-700 hover:text-gray-200',
            )}
          >
            Clear {activeFilterCount} filter{activeFilterCount > 1 ? 's' : ''}
          </button>
        )}
      </div>

      {/* Filter toolbar */}
      <div className={clsx(
        'border rounded-xl p-3 space-y-2',
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
            onChange={e => setSearchInput(e.target.value)}
            className="input w-full !pl-9 !pr-3"
          />
          {searchInput && (
            <button
              onClick={() => setSearchInput('')}
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
          <DatePicker value={dateFrom} onChange={setDateFrom} label="From" />
          <DatePicker value={dateTo} onChange={setDateTo} label="To" />

          <div className="w-px h-6 bg-surface-600 mx-1 hidden sm:block" />

          <select
            value={sportType}
            onChange={e => setSportType(e.target.value)}
            className={selectClass}
          >
            <option value="">All Sports</option>
            {(sportTypes ?? []).map((s: string) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>

          <select
            value={year ?? ''}
            onChange={e => setYear(e.target.value ? Number(e.target.value) : undefined)}
            className={selectClass}
          >
            <option value="">All Years</option>
            {(years ?? []).map((y: number) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>

          <div className="w-px h-6 bg-surface-600 mx-1 hidden sm:block" />

          {/* Sort controls */}
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-gray-500 shrink-0">Sort</span>
            <select
              value={sortBy}
              onChange={e => setSortBy(e.target.value)}
              className={selectClass}
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <button
              onClick={() => setSortDir(d => d === 'desc' ? 'asc' : 'desc')}
              className="btn flex items-center justify-center !px-2"
              title={sortDir === 'desc' ? 'Descending — click for ascending' : 'Ascending — click for descending'}
            >
              <svg className={clsx('w-4 h-4 transition-transform duration-200', sortDir === 'asc' && 'rotate-180')} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Activity list */}
      {isLoading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div
              key={i}
              className={clsx(
                'rounded-xl border p-4 animate-pulse',
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
          'text-center py-16 rounded-xl border',
          isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
        )}>
          <svg className="w-12 h-12 text-gray-600 mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <p className="text-gray-500 text-sm">No activities found</p>
          <p className="text-gray-600 text-xs mt-1">Try adjusting your filters</p>
        </div>
      ) : (
        <>
          <div className={clsx('space-y-2 transition-opacity duration-200 stagger-children', isFetching && !isLoading && 'opacity-60')}>
            {data?.items?.map((a: Record<string, unknown>) => (
              <ActivityCard key={a.id as string} activity={a} />
            ))}
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
                    'w-8 h-8 rounded text-sm font-mono transition-colors',
                    p === page
                      ? isLight
                        ? 'bg-gray-900 text-white'
                        : 'bg-white/10 text-white font-bold'
                      : isLight
                        ? 'text-gray-500 hover:bg-gray-100'
                        : 'text-gray-500 hover:bg-surface-700',
                  )}
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
