import { Link } from 'react-router-dom'
import { usePersonalRecords } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'

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

function formatPrPace(seconds: number, distanceM: number, category: string): string {
  if (category === 'cycling') {
    const kmh = (distanceM / seconds) * 3.6
    return `${kmh.toFixed(1)} km/h`
  }
  if (category === 'swimming') {
    const per100 = (seconds / distanceM) * 100
    const m = Math.floor(per100 / 60)
    const s = Math.round(per100 % 60)
    return `${m}:${s.toString().padStart(2, '0')} /100m`
  }
  const perKm = (seconds / distanceM) * 1000
  const m = Math.floor(perKm / 60)
  const s = Math.round(perKm % 60)
  return `${m}:${s.toString().padStart(2, '0')} /km`
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
  const { data: personalRecords, isLoading } = usePersonalRecords()

  if (isLoading) return <div className="text-gray-500 p-6">Loading personal records...</div>

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h2 className="text-2xl font-bold">Personal Records</h2>

      {personalRecords && Object.keys(personalRecords).length > 0 ? (
        Object.entries(personalRecords).map(([category, records]) => {
          const sportType = SPORT_CATEGORY_SPORT_TYPE[category] ?? category
          const color = getSportColor(sportType)
          return (
            <div key={category} className="bg-surface-800 border border-surface-600 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                <span className="text-xs text-gray-500 uppercase tracking-wider">
                  {SPORT_CATEGORY_LABELS[category] ?? category}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-500 text-xs uppercase border-b border-surface-600">
                      <th className="text-left py-2 pr-3 font-medium">Distance</th>
                      <th className="text-right py-2 px-3 font-medium">Time</th>
                      <th className="text-right py-2 px-3 font-medium">Pace</th>
                      <th className="text-left py-2 px-3 font-medium hidden sm:table-cell">Activity</th>
                      <th className="text-right py-2 pl-3 font-medium hidden sm:table-cell">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(records as PRRecord[]).map((record) => (
                      <tr key={record.distance_m} className="border-b border-surface-700 last:border-b-0">
                        <td className="py-2.5 pr-3 font-medium" style={{ color }}>
                          {record.label}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono font-bold text-gray-200">
                          {formatPrTime(record.time_s)}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-gray-400 text-xs">
                          {formatPrPace(record.time_s, record.distance_m, category)}
                        </td>
                        <td className="py-2.5 px-3 text-left hidden sm:table-cell">
                          <Link
                            to={`/activities/${record.activity_id}`}
                            className="text-xs text-gray-500 hover:text-gray-200 truncate max-w-[180px] inline-block transition-colors"
                          >
                            {record.activity_name}
                          </Link>
                        </td>
                        <td className="py-2.5 pl-3 text-right text-xs text-gray-600 hidden sm:table-cell">
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
        <div className="text-gray-500">No personal records found. Make sure your activities have GPS streams.</div>
      )}
    </div>
  )
}
