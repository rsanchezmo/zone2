import { useMemo } from 'react'
import clsx from 'clsx'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts'
import { useTheme } from '../../hooks/useTheme'
import type { GarminTrends } from '../../api/hooks'
import ChartPanel, { LegendSwatch } from '../shared/ChartPanel'
import { ACCENT, ACCENT_LIGHT, displayNum, num, useGarminChartProps } from './garmin'

/** Weight and its 7-day trend. */
export default function BodySection({ trends: t, days }: { trends: GarminTrends | undefined; days: number }) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const { chartMargin, xAxisProps, yAxisProps, tooltipProps } = useGarminChartProps()

  // Weigh-ins are sparse (manual or scale days only) — keep only real readings
  // so the line connects across gaps instead of breaking on missing days.
  // avg7d is a trailing 7-calendar-day mean over whatever readings exist in
  // that window, smoothing day-to-day water-weight noise into a trend.
  const weightData = useMemo(() => {
    const points = (t?.metrics.body_composition ?? [])
      .map(r => ({ date: r.date, kg: num(r.weight_kg) }))
      .filter((r): r is { date: string; kg: number } => r.kg !== null)
    const dayMs = 86_400_000
    return points.map((p, i) => {
      const end = new Date(p.date + 'T00:00:00').getTime()
      const window = points
        .slice(0, i + 1)
        .filter(q => end - new Date(q.date + 'T00:00:00').getTime() < 7 * dayMs)
      return { ...p, avg7d: window.reduce((s, q) => s + q.kg, 0) / window.length }
    })
  }, [t])

  const weightDelta = weightData.length >= 2
    ? weightData[weightData.length - 1].kg - weightData[0].kg
    : null

  return (
    <>
      {/* ── Weight (full width) ──────────────────────────────── */}
      <div className="section-head pt-2">
        <span className="eyebrow">Body</span>
      </div>
      <ChartPanel
        title="Weight"
        sublabel={`last ${days}d${weightDelta != null ? ` · ${weightDelta >= 0 ? '+' : ''}${weightDelta.toFixed(1)} kg over window` : ''}`}
        accent={ACCENT}
        legend={<>
          <LegendSwatch color={ACCENT} label="Weigh-in" />
          <LegendSwatch color={ACCENT_LIGHT} label="7-day avg" variant="dashed" />
        </>}
      >
        {weightData.length === 0 ? (
          <div className={clsx('flex items-center justify-center h-[220px] text-xs', isLight ? 'text-gray-400' : 'text-gray-500')}>
            No weigh-ins in this window
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={weightData} margin={chartMargin}>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps} domain={['dataMin - 0.5', 'dataMax + 0.5']}
                tickFormatter={(v) => v.toFixed(1)} />
              <Tooltip {...tooltipProps}
                formatter={(v: unknown, name) => [`${displayNum(v).toFixed(1)} kg`, name === 'avg7d' ? '7-day avg' : 'Weight']} />
              <Line type="monotone" dataKey="avg7d"
                stroke={ACCENT_LIGHT} strokeWidth={1.5} strokeDasharray="4 3"
                dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="kg"
                stroke={ACCENT} strokeWidth={2}
                dot={{ r: 2.5, fill: ACCENT, stroke: ACCENT }}
                activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </ChartPanel>
    </>
  )
}
