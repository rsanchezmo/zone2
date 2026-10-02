import { memo, useMemo, useState } from 'react'
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import ChartPanel, { LegendSwatch } from './ChartPanel'
import { useCoverageTimeline } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { useIsMobile } from '../../hooks/useIsMobile'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-09" -> "Sep '26" */
function monthLabel(month: string): string {
  const [y, m] = month.split('-')
  return `${MONTHS[Number(m) - 1]} '${y.slice(2)}`
}

type Range = '1y' | 'all'

/** A city's coverage growth: km of streets run for the first time each month,
 *  with the running total. */
function NewStreetsPanel({ slug, accent }: { slug?: string; accent: string }) {
  const { data } = useCoverageTimeline(slug)
  const { colors } = useTheme()
  const isMobile = useIsMobile()
  const [range, setRange] = useState<Range>('all')

  const months = useMemo(() => data?.months ?? [], [data])
  const shown = useMemo(
    () => (range === '1y' ? months.slice(-12) : months).map(m => ({ ...m, label: monthLabel(m.month) })),
    [months, range],
  )
  if (months.length === 0) return null

  const thisMonth = months[months.length - 1]
  const best = months.reduce((b, m) => (m.new_km > b.new_km ? m : b), months[0])

  return (
    <ChartPanel
      title="New streets"
      sublabel="km run for the first time"
      accent={accent}
      toolbar={
        <div className="flex items-center gap-0.5" role="tablist">
          <button className="chip" data-active={range === '1y'} onClick={() => setRange('1y')}>1Y</button>
          <button className="chip" data-active={range === 'all'} onClick={() => setRange('all')}>All</button>
        </div>
      }
      legend={
        <>
          <LegendSwatch color={accent} label="New per month" variant="solid" />
          <LegendSwatch color={colors.labelColor} label="Total covered" variant="solid" />
        </>
      }
      footer={
        <p className="text-[11px] text-gray-500">
          This month +{thisMonth.new_km.toFixed(1)} km · best {monthLabel(best.month)} (+{best.new_km.toFixed(1)} km) ·{' '}
          {thisMonth.cumulative_km.toFixed(0)} km covered
        </p>
      }
    >
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={shown} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
          <XAxis dataKey="label" tick={{ fill: colors.tickFill, fontSize: 10 }} axisLine={false} tickLine={false}
                 interval="preserveStartEnd" minTickGap={24} />
          <YAxis yAxisId="new" tick={{ fill: colors.tickFillSecondary, fontSize: 10 }} axisLine={false} tickLine={false}
                 width={isMobile ? 28 : 40} tickFormatter={(v: number) => `${v}`} />
          <YAxis yAxisId="total" orientation="right" tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
                 axisLine={false} tickLine={false} width={isMobile ? 32 : 44} tickFormatter={(v: number) => `${v}`} />
          <Tooltip
            {...colors.tooltip}
            formatter={(value: unknown, name: unknown) =>
              name === 'new_km' ? [`+${Number(value).toFixed(1)} km`, 'New streets'] : [`${Number(value).toFixed(1)} km`, 'Total covered']}
          />
          <Bar yAxisId="new" dataKey="new_km" fill={accent} fillOpacity={0.75} radius={[3, 3, 0, 0]} />
          <Line yAxisId="total" dataKey="cumulative_km" stroke={colors.labelColor} strokeOpacity={0.6} strokeWidth={1.5}
                dot={false} type="monotone" />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartPanel>
  )
}

// Its chart needn't redraw on every pan of the coverage map above it
export default memo(NewStreetsPanel)
