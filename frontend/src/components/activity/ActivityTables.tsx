import clsx from 'clsx'
import type { ActivityDetail } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import { useTheme } from '../../hooks/useTheme'
import {
  getSportCategory, convertSpeed, formatPace, formatClockDuration, formatDist, isSpeedSport,
} from '../../utils/formatSpeed'
import ChartPanel from '../shared/ChartPanel'
import { paceUnitOf, type Split } from './activityData'

export function LapsTable({ activity }: { activity: ActivityDetail }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  if (!activity.laps || activity.laps.length <= 1) return null
  const sportCategory = getSportCategory(activity.sport_type)
  const useSpeedUnit = isSpeedSport(activity.sport_type)
  const paceUnit = paceUnitOf(activity.sport_type)
  const sportAccent = getSportColor(activity.sport_type)
  const laps = activity.laps ?? []
  return (
    <ChartPanel title="Laps" accent={sportAccent} glow={false}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs uppercase border-b border-surface-600/50">
              <th className="text-left py-2 pr-3 font-medium">#</th>
              <th className="text-right py-2 px-3 font-medium">Distance</th>
              <th className="text-right py-2 px-3 font-medium">Time</th>
              <th className="text-right py-2 px-3 font-medium">{useSpeedUnit ? 'Speed' : 'Pace'}</th>
              {laps.some(l => l.average_heartrate) && (
                <th className="text-right py-2 px-3 font-medium">Avg HR</th>
              )}
              {laps.some(l => l.max_heartrate) && (
                <th className="text-right py-2 px-3 font-medium">Max HR</th>
              )}
              {laps.some(l => l.average_cadence) && (
                <th className="text-right py-2 px-3 font-medium">Cadence</th>
              )}
            </tr>
          </thead>
          <tbody>
            {laps.map((lap, i) => {
              const lapSpeed = lap.average_speed as number || 0
              const { value: paceVal } = convertSpeed(lapSpeed, activity.sport_type)
              const lapDistRaw = lap.distance as number || 0

              return (
                <tr
                  key={i}
                  className="border-b border-surface-600/30 last:border-b-0"
                >
                  <td className="py-2 pr-3 text-gray-400 font-medium">
                    {i + 1}
                  </td>
                  <td className={clsx('py-2 px-3 text-right font-mono', isLight ? 'text-gray-600' : 'text-gray-300')}>
                    {formatDist(lapDistRaw / 1000, activity.sport_type, 2)}
                  </td>
                  <td className={clsx('py-2 px-3 text-right font-mono', isLight ? 'text-gray-600' : 'text-gray-300')}>
                    {formatClockDuration(lap.moving_time as number || lap.elapsed_time as number || 0)}
                  </td>
                  <td className="py-2 px-3 text-right font-mono">
                    {lapSpeed > 0 ? (
                      <>
                        {formatPace(paceVal, useSpeedUnit)}
                        <span className="text-gray-500 text-xs ml-1">{paceUnit}</span>
                      </>
                    ) : '–'}
                  </td>
                  {laps.some(l => l.average_heartrate) && (
                    <td className="py-2 px-3 text-right text-pink-400 font-mono">
                      {lap.average_heartrate ? Math.round(lap.average_heartrate as number) : '–'}
                    </td>
                  )}
                  {laps.some(l => l.max_heartrate) && (
                    <td className="py-2 px-3 text-right text-pink-400/70 font-mono">
                      {lap.max_heartrate ? Math.round(lap.max_heartrate as number) : '–'}
                    </td>
                  )}
                  {laps.some(l => l.average_cadence) && (
                    <td className="py-2 px-3 text-right text-blue-400 font-mono">
                      {lap.average_cadence ? Math.round((lap.average_cadence as number) * (sportCategory === 'running' ? 2 : 1)) : '–'}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </ChartPanel>
  )
}

export function SplitsTable({ activity, splits, hasGap }: { activity: ActivityDetail; splits: Split[]; hasGap: boolean }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  if (splits.length <= 1) return null
  const sportCategory = getSportCategory(activity.sport_type)
  const useSpeedUnit = isSpeedSport(activity.sport_type)
  const paceUnit = paceUnitOf(activity.sport_type)
  const sportAccent = getSportColor(activity.sport_type)
  const fullSplits = splits.filter((s: Split) => !s.isPartial)
  const bestPace = fullSplits.length > 0
    ? (useSpeedUnit
        ? Math.max(...fullSplits.map((s: Split) => s.avgPace))
        : Math.min(...fullSplits.map((s: Split) => s.avgPace)))
    : null
  const worstPace = fullSplits.length > 0
    ? (useSpeedUnit
        ? Math.min(...fullSplits.map((s: Split) => s.avgPace))
        : Math.max(...fullSplits.map((s: Split) => s.avgPace)))
    : null

  return (
    <ChartPanel title="Splits" accent={sportAccent} glow={false}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs uppercase border-b border-surface-600/50">
              <th className="text-left py-2 pr-3 font-medium">{sportCategory === 'swimming' ? '#' : 'KM'}</th>
              <th className="text-right py-2 px-3 font-medium">{useSpeedUnit ? 'Speed' : 'Pace'}</th>
              {hasGap && (
                <th className="text-right py-2 px-3 font-medium">GAP</th>
              )}
              <th className="text-right py-2 px-3 font-medium">Time</th>
              {splits.some((s: Split) => s.avgHR !== null) && (
                <th className="text-right py-2 px-3 font-medium">HR</th>
              )}
              {splits.some((s: Split) => s.avgCadence !== null) && (
                <th className="text-right py-2 px-3 font-medium">Cadence</th>
              )}
              <th className="text-right py-2 px-3 font-medium">Elev +</th>
              <th className="text-right py-2 pl-3 font-medium">Elev −</th>
            </tr>
          </thead>
          <tbody>
            {splits.map((split: Split) => {
              const isBest = !split.isPartial && bestPace !== null && split.avgPace === bestPace
              const isWorst = !split.isPartial && worstPace !== null && split.avgPace === worstPace

              // Pace bar width relative to range
              const paceRange = bestPace !== null && worstPace !== null ? Math.abs(worstPace - bestPace) : 0
              const barWidth = paceRange > 0 && !split.isPartial
                ? useSpeedUnit
                  ? ((split.avgPace - worstPace!) / paceRange) * 100
                  : ((worstPace! - split.avgPace) / paceRange) * 100
                : 50

              return (
                <tr
                  key={split.km}
                  className="border-b border-surface-600/30 last:border-b-0"
                >
                  <td className="py-2 pr-3 text-gray-400 font-medium">
                    {split.isPartial
                      ? (sportCategory === 'swimming' ? `${Math.round(split.splitDistance)} m` : `${(split.splitDistance / 1000).toFixed(2)}`)
                      : (sportCategory === 'swimming' ? `${Math.round(split.splitDistance)} m` : split.km)}
                  </td>
                  <td className="py-2 px-3 text-right font-mono">
                    <div className="flex items-center justify-end gap-2">
                      <div className={clsx('w-16 h-1.5 rounded-full overflow-hidden hidden sm:block', isLight ? 'bg-gray-200' : 'bg-surface-600')}>
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.max(5, barWidth)}%`,
                            backgroundColor: isBest
                              ? '#22c55e'
                              : isWorst
                                ? '#ff4444'
                                : getSportColor(activity.sport_type),
                          }}
                        />
                      </div>
                      <span className={
                        isBest ? 'text-green-400 font-bold' :
                        isWorst ? 'text-red-400' :
                        ''
                      }>
                        {formatPace(split.avgPace, useSpeedUnit)}
                        <span className="text-gray-500 text-xs ml-1">{paceUnit}</span>
                      </span>
                    </div>
                  </td>
                  {hasGap && (
                    <td className="py-2 px-3 text-right text-orange-400 font-mono">
                      {split.gapPace != null ? formatPace(split.gapPace, false) : '–'}
                      <span className="text-gray-500 text-xs ml-1">{paceUnit}</span>
                    </td>
                  )}
                  <td className={clsx('py-2 px-3 text-right font-mono', isLight ? 'text-gray-600' : 'text-gray-300')}>
                    {formatClockDuration(split.time)}
                  </td>
                  {splits.some((s: Split) => s.avgHR !== null) && (
                    <td className="py-2 px-3 text-right text-pink-400 font-mono">
                      {split.avgHR ?? '–'}
                    </td>
                  )}
                  {splits.some((s: Split) => s.avgCadence !== null) && (
                    <td className="py-2 px-3 text-right text-blue-400 font-mono">
                      {split.avgCadence ?? '–'}
                    </td>
                  )}
                  <td className="py-2 px-3 text-right text-green-400/70 font-mono text-xs">
                    {split.elevGain > 0 ? `+${split.elevGain}m` : '–'}
                  </td>
                  <td className="py-2 pl-3 text-right text-red-400/70 font-mono text-xs">
                    {split.elevLoss > 0 ? `−${split.elevLoss}m` : '–'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </ChartPanel>
  )
}
