import { Link } from 'react-router-dom'
import clsx from 'clsx'
import type { Activity } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import { useTheme } from '../../hooks/useTheme'
import { formatDist } from '../../utils/formatSpeed'
import { parseLocalDate } from '../../utils/dates'
import ChartPanel from '../shared/ChartPanel'

export default function SimilarActivities({ similar, sportType }: { similar: Activity[] | undefined; sportType: string }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  if (!similar || similar.length === 0) return null
  const sportAccent = getSportColor(sportType)

  return (
    <ChartPanel title="Similar activities" accent={sportAccent} glow={false}>
      <div className={clsx('divide-y', isLight ? 'divide-gray-100' : 'divide-surface-700')}>
        {similar.map(sa => (
          <Link
            key={sa.id as number}
            to={`/activities/${sa.id}`}
            className={clsx('flex items-center gap-3 py-2.5 px-1 -mx-1 rounded-lg transition-colors group', isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700')}
          >
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: getSportColor(sa.sport_type as string) }}
            />
            <div className="flex-1 min-w-0">
              <div className={clsx('text-sm truncate transition-colors', isLight ? 'text-gray-800 group-hover:text-gray-900' : 'text-gray-200 group-hover:text-white')}>
                {String(sa.name)}
              </div>
              <div className="text-xs text-gray-500">
                {sa.start_date_local ? parseLocalDate(String(sa.start_date_local)).toLocaleDateString() : ''}
              </div>
            </div>
            <div className="flex items-center gap-4 text-xs text-gray-400 font-mono flex-shrink-0">
              <span>{formatDist((sa.distance_km as number) ?? 0, sa.sport_type as string, 1)}</span>
              {!!sa.formatted_pace && <span>{String(sa.formatted_pace)}</span>}
              {(sa.total_elevation_gain as number) > 0 && (
                <span className="text-green-400/70">+{Math.round(sa.total_elevation_gain as number)}m</span>
              )}
              <span>{String(sa.moving_time_formatted)}</span>
            </div>
          </Link>
        ))}
      </div>
    </ChartPanel>
  )
}
