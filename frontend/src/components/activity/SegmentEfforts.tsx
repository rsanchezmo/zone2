import clsx from 'clsx'
import type { ActivityDetail } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import {
  getSportCategory, convertSpeed, formatPace, formatClockDuration, formatDist, isSpeedSport,
} from '../../utils/formatSpeed'
import { paceUnitOf } from './activityData'

/** Strava segment efforts in this activity, PRs highlighted. */
export default function SegmentEfforts({ activity }: { activity: ActivityDetail }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  if (!activity.segment_efforts || activity.segment_efforts.length === 0) return null
  const sportCategory = getSportCategory(activity.sport_type)
  const useSpeedUnit = isSpeedSport(activity.sport_type)
  const paceUnit = paceUnitOf(activity.sport_type)
  const efforts = activity.segment_efforts ?? []
  return (
    <details
      className={clsx('panel p-5 group', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}
      open
    >
      <summary className="eyebrow cursor-pointer select-none list-none flex items-center justify-between">
        <span>Strava segments · {efforts.length}</span>
        <span className={clsx('text-[10px] transition-transform group-open:rotate-180', isLight ? 'text-gray-400' : 'text-gray-600')}>▼</span>
      </summary>
      <div className="space-y-3 mt-4">
        {efforts.map((effort, i) => {
          const segment = effort.segment
          const name = (effort.name as string) || (segment?.name as string) || `Segment ${i + 1}`
          const elapsed = effort.elapsed_time as number || 0
          const distance = (effort.distance as number || 0)
          const distKm = distance / 1000
          const prRank = effort.pr_rank as number | null
          const avgHR = effort.average_heartrate as number | null
          const maxHR = effort.max_heartrate as number | null
          const avgCadence = effort.average_cadence as number | null
          const avgWatts = effort.average_watts as number | null
          const avgGrade = segment?.average_grade as number | null
          const city = segment?.city as string | null

          // Compute pace
          const speedMs = elapsed > 0 ? distance / elapsed : 0
          const { value: paceVal } = convertSpeed(speedMs, activity.sport_type)
          const paceStr = formatPace(paceVal, useSpeedUnit)

          return (
            <div
              key={i}
              className={clsx(
                'rounded-lg border p-3',
                prRank === 1
                  ? (isLight ? 'border-amber-300 bg-amber-50/50' : 'border-amber-500/40 bg-amber-500/5')
                  : (isLight ? 'border-gray-200' : 'border-surface-600/60'),
              )}
            >
              {/* Top row: name + badges + time */}
              <div className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={clsx('text-sm font-medium truncate', isLight ? 'text-gray-800' : 'text-gray-200')}>{name}</span>
                  {prRank === 1 && (
                    <span className={clsx('text-[10px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0', isLight ? 'bg-amber-100 text-amber-700' : 'bg-amber-500/15 text-amber-400')}>
                      PR
                    </span>
                  )}
                  {prRank != null && prRank > 1 && prRank <= 3 && (
                    <span className={clsx('text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0', isLight ? 'bg-gray-100 text-gray-500' : 'bg-surface-700 text-gray-400')}>
                      {prRank === 2 ? '2nd' : '3rd'}
                    </span>
                  )}
                </div>
                <span className={clsx('text-sm font-mono font-medium flex-shrink-0', isLight ? 'text-gray-800' : 'text-gray-200')}>
                  {formatClockDuration(elapsed)}
                </span>
              </div>

              {/* Stats row */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                <span className={clsx('font-mono', isLight ? 'text-gray-600' : 'text-gray-400')}>
                  {distKm < 1 ? `${Math.round(distance)} m` : formatDist(distKm, activity.sport_type, 2)}
                </span>
                <span className={clsx('font-mono', isLight ? 'text-gray-600' : 'text-gray-400')}>
                  {paceStr} <span className="text-gray-500">{paceUnit}</span>
                </span>
                {avgGrade != null && avgGrade !== 0 && (
                  <span className={clsx('font-mono', avgGrade > 0 ? 'text-green-400/80' : 'text-blue-400/80')}>
                    {avgGrade > 0 ? '+' : ''}{avgGrade.toFixed(1)}%
                  </span>
                )}
                {avgHR != null && (
                  <span className="font-mono text-pink-400/80">
                    {Math.round(avgHR)} bpm
                    {maxHR != null && <span className="text-gray-500"> / {Math.round(maxHR)}</span>}
                  </span>
                )}
                {avgCadence != null && (
                  <span className="font-mono text-blue-400/80">
                    {Math.round(avgCadence * (sportCategory === 'running' ? 2 : 1))} {sportCategory === 'running' ? 'spm' : 'rpm'}
                  </span>
                )}
                {avgWatts != null && (
                  <span className="font-mono text-purple-400/80">
                    {Math.round(avgWatts)} W
                  </span>
                )}
                {city && (
                  <span className="text-gray-500">{city}</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </details>
  )
}
