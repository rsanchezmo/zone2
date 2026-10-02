import clsx from 'clsx'
import type { ActivityDetail } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import { useTheme } from '../../hooks/useTheme'
import {
  getSportCategory, formatPace, formatClockDuration, distValue, getDistUnit,
} from '../../utils/formatSpeed'
import StatCard from '../shared/StatCard'
import ChartPanel from '../shared/ChartPanel'
import { paceUnitOf } from './activityData'

export function ActivityMetrics({ activity, overallGap }: { activity: ActivityDetail; overallGap: number | null }) {
  const sportCategory = getSportCategory(activity.sport_type)
  const paceUnit = paceUnitOf(activity.sport_type)

  return (
    <section>
      <div className="section-head mb-4"><span className="eyebrow">Metrics</span></div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger-children">
      <StatCard label="Distance" value={distValue(activity.distance_km ?? 0, activity.sport_type, 2)} unit={getDistUnit(activity.sport_type)} />
      <StatCard label="Moving Time" value={activity.moving_time_formatted ?? ''} />
      {activity.elapsed_time_formatted && activity.elapsed_time !== activity.moving_time && (
        <StatCard label="Elapsed Time" value={activity.elapsed_time_formatted} />
      )}
      {activity.formatted_pace && <StatCard label="Pace" value={activity.formatted_pace} />}
      {activity.formatted_max_speed && <StatCard label="Max Speed" value={activity.formatted_max_speed} />}
      <StatCard label="Elevation" value={Math.round(activity.total_elevation_gain ?? 0)} unit="m" />
      {activity.average_heartrate && (
        <StatCard label="Avg HR" value={Math.round(activity.average_heartrate)} unit="bpm" color="text-pink-400" />
      )}
      {activity.max_heartrate && (
        <StatCard label="Max HR" value={Math.round(activity.max_heartrate)} unit="bpm" color="text-pink-400" />
      )}
      {activity.average_cadence && (
        <StatCard
          label="Cadence"
          value={Math.round(activity.average_cadence * (sportCategory === 'running' ? 2 : 1))}
          unit={sportCategory === 'running' ? 'spm' : 'rpm'}
          color="text-blue-400"
        />
      )}
      {activity.suffer_score && (
        <StatCard label="Suffer Score" value={activity.suffer_score} color="text-amber-400" />
      )}
      {overallGap != null && (
        <StatCard label="GAP" value={formatPace(overallGap, false)} unit={paceUnit} color="text-orange-400" />
      )}
      {activity.calories && (
        <StatCard label="Calories" value={Math.round(activity.calories)} unit="kcal" color="text-orange-400" />
      )}
      {activity.average_watts && (
        <StatCard label="Avg Power" value={Math.round(activity.average_watts)} unit="W" color="text-purple-400" />
      )}
      {activity.weighted_average_watts && (
        <StatCard label="NP" value={Math.round(activity.weighted_average_watts)} unit="W" color="text-purple-400" />
      )}
      {activity.max_watts && (
        <StatCard label="Max Power" value={Math.round(activity.max_watts)} unit="W" color="text-purple-400" />
      )}
      </div>
    </section>
  )
}

export function BestEfforts({ activity }: { activity: ActivityDetail }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  if (!activity.best_efforts || activity.best_efforts.length === 0) return null
  const sportAccent = getSportColor(activity.sport_type)

  return (
    <ChartPanel title="Best efforts" accent={sportAccent} glow={false}>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
        {activity.best_efforts.map((effort, i) => {
          const prRank = effort.pr_rank as number | null
          return (
            <div
              key={i}
              className={clsx(
                'flex items-center justify-between px-3 py-2 rounded-lg border text-sm font-mono tabular-nums',
                prRank === 1
                  ? (isLight ? 'border-amber-300 bg-amber-50' : 'border-amber-500/40 bg-amber-500/10')
                  : prRank === 2
                    ? (isLight ? 'border-gray-300 bg-gray-50' : 'border-gray-400/30 bg-gray-400/10')
                    : prRank === 3
                      ? (isLight ? 'border-orange-300 bg-orange-50' : 'border-orange-500/30 bg-orange-500/10')
                      : (isLight ? 'border-gray-200' : 'border-surface-600'),
              )}
            >
              <span className={clsx('text-xs', isLight ? 'text-gray-600' : 'text-gray-400')}>
                {effort.name as string}
              </span>
              <div className="flex items-center gap-1.5">
                <span className={isLight ? 'text-gray-800' : 'text-gray-200'}>
                  {formatClockDuration(effort.elapsed_time as number)}
                </span>
                {prRank === 1 && <span className="text-amber-400 text-xs font-bold">PR</span>}
                {prRank === 2 && <span className="text-gray-400 text-[10px]">2nd</span>}
                {prRank === 3 && <span className="text-orange-400 text-[10px]">3rd</span>}
              </div>
            </div>
          )
        })}
      </div>
    </ChartPanel>
  )
}
