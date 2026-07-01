import { useMemo } from 'react'
import {
  ComposedChart, Area, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { useWeeklyRelativeEffort } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { useIsMobile } from '../../hooks/useIsMobile'
import { getSportColor } from '../../constants/sportColors'
import ChartPanel from './ChartPanel'
import clsx from 'clsx'

interface WeekPoint {
  week_start: string
  relative_effort: number
  band_low: number
  band_high: number
  status: 'below' | 'in_range' | 'above'
}

const STATUS_META: Record<WeekPoint['status'], { label: string; color: string }> = {
  below: { label: 'Below range', color: '#38bdf8' },
  in_range: { label: 'In range', color: '#22c55e' },
  above: { label: 'Above range', color: '#a78bfa' },
}

const WEEKS_SHOWN = 52

// Weekly Relative Effort (HR-zone-weighted training load) with a personalized
// expected-range band. Renders nothing when the endpoint returns no weeks — e.g.
// the selected sport isn't running/swimming — so the parent can drop it in
// unconditionally.
export default function RelativeEffortChart({ sportType }: { sportType?: string }) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const isMobile = useIsMobile()
  const { data, isLoading } = useWeeklyRelativeEffort(sportType || undefined)
  const accent = sportType ? getSportColor(sportType) : '#a78bfa'

  const weeks: WeekPoint[] = useMemo(() => (data?.weeks ?? []).slice(-WEEKS_SHOWN), [data])
  const chartData = useMemo(
    () => weeks.map(w => ({ date: w.week_start, re: w.relative_effort, low: w.band_low, high: w.band_high })),
    [weeks],
  )
  const latest = weeks[weeks.length - 1]

  if (isLoading) {
    return <div className={clsx('h-[300px] rounded-xl animate-pulse', isLight ? 'bg-gray-100' : 'bg-surface-700/50')} />
  }
  if (!weeks.length) return null

  const statusPill = latest ? (
    <span
      className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
      style={{ color: STATUS_META[latest.status].color, background: `${STATUS_META[latest.status].color}1f` }}
    >
      {Math.round(latest.relative_effort)} · {STATUS_META[latest.status].label}
    </span>
  ) : undefined

  return (
    <ChartPanel title="Relative effort" sublabel={sportType || 'run + swim'} accent={accent} status={statusPill}>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
          <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fill: colors.tickFill, fontSize: 10 }}
            tickFormatter={(v: string) => new Date(v).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })}
            interval={chartData.length <= 14 ? 0 : Math.floor(chartData.length / 10)}
            axisLine={false}
            tickLine={false}
            minTickGap={20}
          />
          <YAxis
            tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
            width={isMobile ? 30 : 40}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: colors.labelColor }}
            itemStyle={{ color: colors.labelColor }}
            formatter={((v: number | number[] | undefined, name: string): [string, string] | undefined => {
              if (v == null) return undefined
              if (name === 'RE') return [String(Math.round(v as number)), 'Relative effort']
              if (name === 'Range' && Array.isArray(v)) return [`${Math.round(v[0])} – ${Math.round(v[1])}`, 'Expected range']
              return undefined
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
            }) as any}
            labelFormatter={(v) => new Date(String(v)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
          />
          {/* Expected-range band: dataKey returns [low, high] so Recharts fills between them. */}
          <Area
            type="monotone"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            dataKey={(d: any) => [d.low, d.high]}
            name="Range"
            stroke="none"
            fill={isLight ? '#94a3b8' : '#64748b'}
            fillOpacity={isLight ? 0.22 : 0.28}
            isAnimationActive={false}
            activeDot={false}
          />
          <Scatter name="RE" dataKey="re" fill={accent} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartPanel>
  )
}
