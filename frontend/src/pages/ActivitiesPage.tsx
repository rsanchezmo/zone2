import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useActivities, useSportTypes, useYears } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'

export default function ActivitiesPage() {
  const [page, setPage] = useState(1)
  const [sportType, setSportType] = useState<string>('')
  const [year, setYear] = useState<number | undefined>()

  const { data: sportTypes } = useSportTypes()
  const { data: years } = useYears()
  const { data, isLoading } = useActivities(page, 20, sportType || undefined, year)

  const totalPages = data ? Math.ceil(data.total / data.per_page) : 0

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Activities</h2>
        <div className="flex gap-2">
          <select
            value={sportType}
            onChange={e => { setSportType(e.target.value); setPage(1) }}
            className="bg-surface-700 border border-surface-600 rounded px-2 py-1 text-sm"
          >
            <option value="">All Sports</option>
            {(sportTypes ?? []).map((s: string) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            value={year ?? ''}
            onChange={e => { setYear(e.target.value ? Number(e.target.value) : undefined); setPage(1) }}
            className="bg-surface-700 border border-surface-600 rounded px-2 py-1 text-sm"
          >
            <option value="">All Years</option>
            {(years ?? []).map((y: number) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="text-gray-500">Loading...</div>
      ) : (
        <>
          <div className="text-sm text-gray-500">{data?.total ?? 0} activities</div>

          <div className="space-y-2">
            {data?.items?.map((a: Record<string, unknown>) => (
              <Link
                key={a.id as string}
                to={`/activities/${a.id}`}
                className="block bg-surface-800 border border-surface-600 rounded-xl p-4 hover:border-neon-red/40 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-medium">{a.name as string}</div>
                    <div className="text-sm text-gray-400 mt-1 flex items-center gap-3">
                      <span className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: getSportColor(a.sport_type as string) }} />
                        <span style={{ color: getSportColor(a.sport_type as string) }}>{a.sport_type as string}</span>
                      </span>
                      <span>{a.distance_km as string} km</span>
                      <span>{a.moving_time_formatted as string}</span>
                      {a.formatted_pace ? <span>{String(a.formatted_pace)}</span> : null}
                    </div>
                  </div>
                  <div className="text-xs text-gray-500">
                    {a.start_date_local ? new Date(a.start_date_local as string).toLocaleDateString() : ''}
                  </div>
                </div>
                {a.total_elevation_gain ? (
                  <div className="text-xs text-gray-500 mt-2">
                    {Math.round(a.total_elevation_gain as number)}m elevation
                    {a.average_heartrate ? ` · ${Math.round(a.average_heartrate as number)} bpm avg` : ''}
                  </div>
                ) : null}
              </Link>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1 bg-surface-700 rounded text-sm disabled:opacity-30"
              >
                Prev
              </button>
              <span className="text-sm text-gray-400">
                {page} / {totalPages}
              </span>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1 bg-surface-700 rounded text-sm disabled:opacity-30"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
