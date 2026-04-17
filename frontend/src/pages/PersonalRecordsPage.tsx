import { Link } from 'react-router-dom'
import { usePersonalRecords, useSportTotals } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { formatPrPace } from '../utils/formatSpeed'
import ChartPanel from '../components/shared/ChartPanel'
import { useTheme } from '../hooks/useTheme'
import clsx from 'clsx'

const SPORT_CATEGORY_LABELS: Record<string, string> = {
  running: 'Running',
  cycling: 'Cycling',
  swimming: 'Swimming',
}

const SPORT_CATEGORY_SPORT_TYPE: Record<string, string> = {
  running: 'Run',
  cycling: 'Ride',
  swimming: 'Swim',
}

function formatPrTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.round(seconds % 60)
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatTotalTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h >= 24) {
    const days = Math.floor(h / 24)
    const remH = h % 24
    if (days > 0 && remH > 0) return `${days}d ${remH}h`
    if (days > 0) return `${days}d`
    return `${remH}h ${m}m`
  }
  return `${h}h ${m}m`
}

function formatDistance(km: number, category?: string): string {
  if (category === 'swimming') {
    const m = Math.round(km * 1000)
    return `${m.toLocaleString()} m`
  }
  return `${km.toLocaleString(undefined, { maximumFractionDigits: 1 })} km`
}

interface PRRecord {
  distance_m: number
  label: string
  time_s: number
  activity_id: string | number
  activity_name: string
  date: string
}

export default function PersonalRecordsPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { data: personalRecords, isLoading } = usePersonalRecords()
  const { data: sportTotals } = useSportTotals()

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-10 pb-12">
        <PageHeader />
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className={clsx(
              'panel p-5 animate-pulse',
              isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
            )}
          >
            <div className={clsx('h-3 w-24 rounded mb-5', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, j) => (
                <div key={j} className={clsx('h-6 rounded', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
              ))}
            </div>
          </div>
        ))}
      </div>
    )
  }

  const hasRecords = personalRecords && Object.keys(personalRecords).length > 0

  return (
    <div className="max-w-4xl mx-auto space-y-10 pb-12">
      <PageHeader />

      {hasRecords ? (
        Object.entries(personalRecords).map(([category, records]) => {
          const sportType = SPORT_CATEGORY_SPORT_TYPE[category] ?? category
          const color = getSportColor(sportType)
          const totals = sportTotals?.[category] as { distance_km: number; time_s: number; count: number } | undefined
          const label = SPORT_CATEGORY_LABELS[category] ?? category
          return (
            <ChartPanel
              key={category}
              title={label}
              accent={color}
              status={
                <span
                  className="inline-block w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: color }}
                  aria-hidden="true"
                />
              }
              toolbar={
                totals ? (
                  <div className={clsx('hidden sm:flex items-center gap-4 text-[11px] font-mono tabular-nums', isLight ? 'text-gray-500' : 'text-gray-400')}>
                    <TotalCell label="Activities" value={totals.count.toLocaleString()} />
                    <span className={clsx('w-px h-4', isLight ? 'bg-gray-200' : 'bg-surface-600')} aria-hidden="true" />
                    <TotalCell label="Distance" value={formatDistance(totals.distance_km, category)} accent={color} />
                    <span className={clsx('w-px h-4', isLight ? 'bg-gray-200' : 'bg-surface-600')} aria-hidden="true" />
                    <TotalCell label="Time" value={formatTotalTime(totals.time_s)} />
                  </div>
                ) : undefined
              }
              glow={false}
            >
              {/* Mobile totals — stacked under header, hidden on sm+ */}
              {totals && (
                <div className={clsx(
                  'sm:hidden grid grid-cols-3 mb-4 -mt-1',
                  isLight ? 'divide-x divide-gray-200' : 'divide-x divide-surface-600',
                )}>
                  <TotalCellBlock label="Activities" value={totals.count.toLocaleString()} />
                  <TotalCellBlock label="Distance" value={formatDistance(totals.distance_km, category)} accent={color} />
                  <TotalCellBlock label="Time" value={formatTotalTime(totals.time_s)} />
                </div>
              )}

              <div>
                {(records as PRRecord[]).map(record => (
                  <PRRow key={record.distance_m} record={record} color={color} category={category} />
                ))}
              </div>
            </ChartPanel>
          )
        })
      ) : (
        <div
          className={clsx(
            'panel p-10 flex flex-col items-center justify-center gap-3 text-center',
            isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
          )}
        >
          <svg
            className={clsx('w-9 h-9', isLight ? 'text-gray-300' : 'text-gray-600')}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 18.75h-9m9 0a3 3 0 013 3h-15a3 3 0 013-3m9 0v-4.5A3.375 3.375 0 0012.75 10.5h-1.5A3.375 3.375 0 007.875 13.875v4.875m9 0H7.875" />
          </svg>
          <p className={clsx('text-sm', isLight ? 'text-gray-500' : 'text-gray-500')}>No personal records found</p>
          <p className={clsx('text-xs', isLight ? 'text-gray-400' : 'text-gray-600')}>
            Make sure your activities have GPS streams — run a stream backfill from the Profile page.
          </p>
        </div>
      )}
    </div>
  )
}

// ────────────────────────────────────────────────────────
// Page header — breadcrumb style matching Dashboard
// ────────────────────────────────────────────────────────

function PageHeader() {
  return (
    <header className="flex items-baseline gap-2">
      <span className="eyebrow">Records</span>
      <span className="text-[11px] text-gray-700">·</span>
      <span className="text-[11px] text-gray-500 normal-case tracking-normal">best efforts across standard distances</span>
    </header>
  )
}

// ────────────────────────────────────────────────────────
// TotalCell — one segment of the totals strip in panel header
// ────────────────────────────────────────────────────────

function TotalCell({ label, value, accent }: { label: string; value: string; accent?: string }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className={clsx('uppercase text-[10px] tracking-[0.15em]', isLight ? 'text-gray-400' : 'text-gray-600')}>{label}</span>
      <span
        className={clsx('font-semibold', accent ? '' : (isLight ? 'text-gray-700' : 'text-gray-200'))}
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </span>
    </span>
  )
}

function TotalCellBlock({ label, value, accent }: { label: string; value: string; accent?: string }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  return (
    <div className="px-3 py-1 first:pl-0 last:pr-0">
      <div className="eyebrow mb-1">{label}</div>
      <div
        className={clsx('text-sm font-mono tabular-nums font-semibold', accent ? '' : (isLight ? 'text-gray-900' : 'text-gray-100'))}
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────
// PRRow — single personal record row
// ────────────────────────────────────────────────────────

function PRRow({ record, color, category }: { record: PRRecord; color: string; category: string }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const pace = formatPrPace(record.time_s, record.distance_m, category)
  const time = formatPrTime(record.time_s)
  const date = record.date
    ? new Date(record.date).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    : null

  return (
    <Link
      to={`/activities/${record.activity_id}`}
      className={clsx(
        'telemetry-row group transition-colors -mx-2 px-2 rounded-md',
        isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700/40',
      )}
      style={{ borderTopColor: isLight ? undefined : undefined }}
    >
      {/* Left: distance label in accent + activity name underneath */}
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <span
          className="font-semibold text-sm tabular-nums shrink-0"
          style={{ color, fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.01em' }}
        >
          {record.label}
        </span>
        <span
          className={clsx(
            'text-xs truncate hidden sm:inline transition-colors',
            isLight ? 'text-gray-400 group-hover:text-gray-700' : 'text-gray-500 group-hover:text-gray-300',
          )}
        >
          {record.activity_name}
        </span>
      </div>

      {/* Right: time (hero) + pace + date, right-aligned */}
      <div className="flex items-baseline gap-4 shrink-0 tabular-nums">
        {pace && (
          <span className={clsx('text-[11px] font-mono hidden sm:inline', isLight ? 'text-gray-400' : 'text-gray-500')}>
            {pace}
          </span>
        )}
        <span className={clsx('font-mono font-semibold text-sm', isLight ? 'text-gray-900' : 'text-gray-100')}>
          {time}
        </span>
        {date && (
          <span className={clsx('text-[11px] font-mono hidden md:inline w-[86px] text-right', isLight ? 'text-gray-400' : 'text-gray-600')}>
            {date}
          </span>
        )}
      </div>
    </Link>
  )
}
