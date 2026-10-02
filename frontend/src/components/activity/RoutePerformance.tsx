import clsx from 'clsx'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import type { ActivityDetail } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import { useTheme } from '../../hooks/useTheme'
import { convertSpeed, formatPace, isSpeedSport } from '../../utils/formatSpeed'
import ChartPanel from '../shared/ChartPanel'
import { paceUnitOf } from './activityData'

/** This effort against Strava's earlier efforts on the same route. */
export default function RoutePerformance({ activity }: { activity: ActivityDetail }) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  if (!activity.similar_activities || activity.similar_activities.effort_count <= 1) return null
  const useSpeedUnit = isSpeedSport(activity.sport_type)
  const paceUnit = paceUnitOf(activity.sport_type)
  const sportAccent = getSportColor(activity.sport_type)
  const sa = activity.similar_activities!
  const trend = sa.trend
  const currentSpeed = activity.average_speed as number
  const sportColor = getSportColor(activity.sport_type)
  const isPaceSport = !useSpeedUnit

  const fmtPaceValue = (v: number) => formatPace(v, useSpeedUnit)

  const trendDir = trend?.direction ?? 0
  const trendLabel = trendDir > 0 ? 'Faster' : trendDir < 0 ? 'Slower' : 'Stable'
  const trendArrow = trendDir > 0 ? '↗' : trendDir < 0 ? '↘' : '→'
  const trendPillClass = trendDir > 0
    ? (isLight ? 'bg-green-50 text-green-700 border-green-200' : 'bg-green-500/10 text-green-400 border-green-500/30')
    : trendDir < 0
      ? (isLight ? 'bg-red-50 text-red-700 border-red-200' : 'bg-red-500/10 text-red-400 border-red-500/30')
      : (isLight ? 'bg-gray-100 text-gray-600 border-gray-200' : 'bg-surface-700 text-gray-400 border-surface-600')

  // Chart data: convert speed (m/s) → pace/speed display values, with labels
  const chartData = trend && trend.speeds.length > 1
    ? trend.speeds.map((s, i) => {
        const speed = i === trend.current_activity_index ? currentSpeed : s
        const { value } = convertSpeed(speed, activity.sport_type)
        return {
          effort: i + 1,
          value: Math.round(value * 100) / 100,
          label: fmtPaceValue(Math.round(value * 100) / 100),
          isCurrent: i === trend.current_activity_index,
        }
      })
    : []
  const statusPills = (
    <div className="flex items-center gap-1.5 flex-wrap">
      {sa.pr_rank === 1 && (
        <span className={clsx('text-[10px] font-bold px-2 py-0.5 rounded-full border', isLight ? 'bg-amber-50 text-amber-600 border-amber-200' : 'bg-amber-500/15 text-amber-400 border-amber-500/30')}>
          PR
        </span>
      )}
      {sa.pr_rank != null && sa.pr_rank > 1 && (
        <span className={clsx('text-[10px] px-2 py-0.5 rounded-full', isLight ? 'bg-gray-100 text-gray-500' : 'bg-surface-700 text-gray-500')}>
          #{sa.pr_rank}/{sa.effort_count}
        </span>
      )}
      {trend && (
        <span className={clsx('text-[10px] font-medium px-2 py-0.5 rounded-full border', trendPillClass)}>
          {trendArrow} {trendLabel}
        </span>
      )}
    </div>
  )
  return (
    <ChartPanel
      title="Route performance"
      accent={sportAccent}
      status={statusPills}
      toolbar={
        <span className={clsx('text-[10px] uppercase tracking-[0.15em]', isLight ? 'text-gray-400' : 'text-gray-500')}>
          {sa.effort_count} efforts
        </span>
      }
      glow={false}
    >
      {chartData.length > 0 && (
        <div className="h-[150px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 16, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="routePerfGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={sportColor} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={sportColor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="effort"
                type="number"
                domain={[0.5, chartData.length + 0.5]}
                hide
              />
              <YAxis
                hide
                domain={(() => {
                  const vals = chartData.map(d => d.value)
                  const min = Math.min(...vals)
                  const max = Math.max(...vals)
                  const range = max - min || 0.2
                  return isPaceSport
                    ? [max + range, min - range]
                    : [min - range, max + range]
                })()}
                allowDataOverflow
              />
              <Tooltip
                {...colors.tooltip}
                labelFormatter={v => `Effort #${v}`}
                formatter={(v: number | undefined) => [fmtPaceValue(v ?? 0) + ` ${paceUnit}`, isPaceSport ? 'Pace' : 'Speed']}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke={sportColor}
                fill="url(#routePerfGrad)"
                strokeWidth={1.5}
                baseValue={isPaceSport ? 'dataMax' : 'dataMin'}
                dot={({ cx, cy, index, payload }: { cx?: number; cy?: number; index?: number; payload?: { isCurrent: boolean }; [key: string]: unknown }) => {
                  const isCurrent = payload?.isCurrent
                  return (
                    <circle
                      key={index}
                      cx={cx} cy={cy}
                      r={isCurrent ? 5 : 3}
                      fill={isCurrent ? (sa.pr_rank === 1 ? '#f59e0b' : sportColor) : (isLight ? '#d1d5db' : '#4b5563')}
                      stroke={isCurrent ? (isLight ? '#fff' : '#111') : 'none'}
                      strokeWidth={isCurrent ? 2 : 0}
                    />
                  )
                }}
                label={(props: unknown) => {
                  const { x = 0, y = 0, index = 0, value = 0 } = props as {
                    x?: number | string
                    y?: number | string
                    index?: number
                    value?: number | string
                  }
                  const xNum = Number(x)
                  const yNum = Number(y)
                  const valueNum = Number(value)
                  const isCurrent = index != null ? chartData[index]?.isCurrent : false
                  return (
                    <text
                      key={index}
                      x={xNum}
                      y={yNum - 8}
                      textAnchor="middle"
                      fontSize={9}
                      fontFamily="ui-monospace, monospace"
                      fontWeight={isCurrent ? 'bold' : 'normal'}
                      fill={isCurrent
                        ? (sa.pr_rank === 1 ? '#f59e0b' : sportColor)
                        : colors.tickFill}
                    >
                      {fmtPaceValue(valueNum)}
                    </text>
                  )
                }}
                activeDot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartPanel>
  )
}
