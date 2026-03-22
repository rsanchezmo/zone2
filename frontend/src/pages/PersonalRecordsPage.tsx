import { Link } from 'react-router-dom'
import { usePersonalRecords, useSportTotals } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { formatPrPace, formatDist } from '../utils/formatSpeed'
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
    if (days > 0 && remH > 0) return `${days}d ${remH}h ${m}m`
    if (days > 0) return `${days}d ${m}m`
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

  const cardClass = clsx(
    'rounded-xl p-4 border',
    isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
  )

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-6">
        <h2 className="page-title">Personal Records</h2>
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className={clsx(cardClass, 'animate-pulse')}>
            <div className="flex items-center gap-2 mb-4">
              <div className={clsx('w-2.5 h-2.5 rounded-full', isLight ? 'bg-gray-200' : 'bg-surface-600')} />
              <div className={clsx('h-3 w-20 rounded', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
            </div>
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, j) => (
                <div key={j} className={clsx('h-5 rounded', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
              ))}
            </div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h2 className="page-title">Personal Records</h2>

      {personalRecords && Object.keys(personalRecords).length > 0 ? (
        Object.entries(personalRecords).map(([category, records]) => {
          const sportType = SPORT_CATEGORY_SPORT_TYPE[category] ?? category
          const color = getSportColor(sportType)
          const totals = sportTotals?.[category] as { distance_km: number; time_s: number; count: number } | undefined
          return (
            <div key={category} className={cardClass}>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                  <span className={clsx('text-xs uppercase tracking-wider', isLight ? 'text-gray-500' : 'text-gray-500')}>
                    {SPORT_CATEGORY_LABELS[category] ?? category}
                  </span>
                </div>
                {totals && (
                  <div className="flex items-center gap-4 text-xs">
                    <span className={clsx('font-mono', isLight ? 'text-gray-500' : 'text-gray-400')}>
                      {totals.count} activities
                    </span>
                    <span className="font-mono font-semibold" style={{ color }}>
                      {formatDistance(totals.distance_km, category)}
                    </span>
                    <span className={clsx('font-mono', isLight ? 'text-gray-500' : 'text-gray-400')}>
                      {formatTotalTime(totals.time_s)}
                    </span>
                  </div>
                )}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className={clsx('text-gray-500 text-xs uppercase border-b', isLight ? 'border-gray-200' : 'border-surface-600')}>
                      <th className="text-left py-2 pr-3 font-medium">Distance</th>
                      <th className="text-right py-2 px-3 font-medium">Time</th>
                      <th className="text-right py-2 px-3 font-medium">Pace</th>
                      <th className="text-left py-2 px-3 font-medium hidden sm:table-cell">Activity</th>
                      <th className="text-right py-2 pl-3 font-medium hidden sm:table-cell">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(records as PRRecord[]).map((record) => (
                      <tr
                        key={record.distance_m}
                        className={clsx(
                          'border-b last:border-b-0 transition-colors',
                          isLight ? 'border-gray-100 hover:bg-gray-50' : 'border-surface-700 hover:bg-surface-700/50',
                        )}
                      >
                        <td className="py-2.5 pr-3 font-medium" style={{ color }}>
                          {record.label}
                        </td>
                        <td className={clsx('py-2.5 px-3 text-right font-mono font-bold', isLight ? 'text-gray-900' : 'text-gray-200')}>
                          {formatPrTime(record.time_s)}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-gray-400 text-xs">
                          {formatPrPace(record.time_s, record.distance_m, category)}
                        </td>
                        <td className="py-2.5 px-3 text-left hidden sm:table-cell">
                          <Link
                            to={`/activities/${record.activity_id}`}
                            className={clsx(
                              'text-xs truncate max-w-[180px] inline-block transition-colors',
                              isLight ? 'text-gray-500 hover:text-gray-900' : 'text-gray-500 hover:text-gray-200',
                            )}
                          >
                            {record.activity_name}
                          </Link>
                        </td>
                        <td className={clsx('py-2.5 pl-3 text-right text-xs hidden sm:table-cell', isLight ? 'text-gray-400' : 'text-gray-600')}>
                          {record.date ? new Date(record.date).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : ''}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })
      ) : (
        <div className={clsx(cardClass, 'flex flex-col items-center justify-center py-12 gap-3')}>
          <svg className={clsx('w-10 h-10', isLight ? 'text-gray-300' : 'text-gray-600')} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 18.75h-9m9 0a3 3 0 013 3h-15a3 3 0 013-3m9 0v-4.5A3.375 3.375 0 0012.75 10.5h-1.5A3.375 3.375 0 007.875 13.875v4.875m9 0H7.875" />
          </svg>
          <p className={clsx('text-sm', isLight ? 'text-gray-500' : 'text-gray-500')}>No personal records found</p>
          <p className={clsx('text-xs', isLight ? 'text-gray-400' : 'text-gray-600')}>Make sure your activities have GPS streams</p>
        </div>
      )}
    </div>
  )
}
