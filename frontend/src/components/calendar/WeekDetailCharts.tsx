import { useMemo } from 'react'
import { type WeeklyReport, type HrZoneBound } from '../../api/hooks'
import { getSportColor, DEFAULT_SPORT_COLOR } from '../../constants/sportColors'
import { formatDist, formatDurationHM } from '../../utils/formatSpeed'
import { WEEKDAYS_SHORT } from '../../constants/weekdays'
import clsx from 'clsx'
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, PieChart,
  Pie, Cell,
} from 'recharts'
import { useTheme } from '../../hooks/useTheme'
import HrZoneDistributionChart from '../shared/HrZoneDistributionChart'

/* ── Sport Pie Chart ────────────────────────────────── */
function SportPieChart({ title, data, formatValue, colorMap }: {
  title: string
  data: Record<string, number>
  formatValue: (v: number, sport?: string) => string
  colorMap: Record<string, string>
}) {
  const { colors } = useTheme()
  const pieData = useMemo(() => {
    return Object.entries(data)
      .filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([name, value]) => ({
        name,
        value: Math.round(value * 10) / 10,
        color: colorMap[name] ?? DEFAULT_SPORT_COLOR,
      }))
  }, [data, colorMap])

  if (pieData.length === 0) return null

  const renderLabel = (props: unknown) => {
    const { cx, cy, midAngle, innerRadius, outerRadius, value, name } = props as {
      cx: number
      cy: number
      midAngle: number
      innerRadius: number
      outerRadius: number
      value: number
      name: string
    }
    const RADIAN = Math.PI / 180
    const radius = innerRadius + (outerRadius - innerRadius) * 0.4
    const x = cx + radius * Math.cos(-midAngle * RADIAN)
    const y = cy + radius * Math.sin(-midAngle * RADIAN)
    return (
      <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={10} fontFamily="monospace" fontWeight="bold">
        {formatValue(value, name)}
      </text>
    )
  }

  return (
    <div className="panel p-4">
      <div className="eyebrow mb-2">{title}</div>
      <div className="flex gap-3 mb-2 flex-wrap">
        {pieData.map(d => (
          <div key={d.name} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.color }} />
            <span className="text-[11px] text-gray-400">{d.name}</span>
          </div>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie
            data={pieData}
            dataKey="value"
            cx="50%"
            cy="50%"
            innerRadius={15}
            outerRadius={75}
            strokeWidth={2}
            stroke="none"
            label={renderLabel}
            labelLine={false}
          >
            {pieData.map((d, i) => (
              <Cell key={i} fill={d.color} fillOpacity={0.7} stroke={d.color} strokeWidth={1} strokeOpacity={0.3} />
            ))}
          </Pie>
          <Tooltip
            {...colors.tooltip}
            formatter={(value, name) => [formatValue(Number(value), String(name)), String(name)]}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ── Accumulated Chart ──────────────────────────────── */
interface AccumulatedChartProps {
  data: Record<string, Record<string, number>>
  previous?: Record<string, Record<string, number>>
  titles?: Record<string, Record<string, string[]>>
  colorMap: Record<string, string>
}

function AccumulatedChart({ data, previous, titles, colorMap }: AccumulatedChartProps) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const totalColor = isLight ? '#111827' : '#f3f4f6'
  const prevColor = isLight ? '#9ca3af' : '#6b7280'
  const {
    chartData, sports, sportColorMap, activeDays, weekTotal, prevWeekTotal, axisStep, axisMax, axisTicks,
  } = useMemo(() => {
    const sportTotals = Object.entries(data).map(([sport, days]) => ({
      sport,
      total: Object.values(days).reduce((a, b) => a + b, 0),
    }))
    sportTotals.sort((a, b) => b.total - a.total)
    const sports = sportTotals.map(s => s.sport)
    const sportColorMap: Record<string, string> = {}
    sports.forEach((s) => { sportColorMap[s] = colorMap[s] ?? getSportColor(s) })

    const activeDays: Record<string, Set<number>> = {}
    for (const sport of sports) {
      activeDays[sport] = new Set()
      for (let d = 0; d < 7; d++) {
        if ((data[sport]?.[d] ?? 0) > 0) activeDays[sport].add(d)
      }
    }

    // Running all-sport total per weekday; null when the week has no counterpart to compare against.
    const runningTotals = (src?: Record<string, Record<string, number>>) => {
      if (!src) return null
      const out: number[] = []
      let running = 0
      for (let d = 0; d < 7; d++) {
        for (const days of Object.values(src)) running += days?.[d] ?? 0
        out.push(Math.round(running))
      }
      return out
    }
    const totals = runningTotals(data) ?? []
    const prevTotals = runningTotals(previous)

    const chartData = WEEKDAYS_SHORT.map((day, dayIdx) => {
      const point: Record<string, unknown> = { day, _dayIdx: dayIdx, _total: totals[dayIdx] ?? 0 }
      if (prevTotals) point._prevTotal = prevTotals[dayIdx]
      for (const sport of sports) {
        let accum = 0
        for (let d = 0; d <= dayIdx; d++) {
          accum += data[sport]?.[d] ?? 0
        }
        point[sport] = Math.round(accum)
      }
      return point
    })

    // The busier of the two weeks tops the axis exactly, so the panel is never padded out
    // to a rounded ceiling. Interior ticks stay on round intervals under that peak.
    const axisMax = Math.max(totals[6] ?? 0, prevTotals?.[6] ?? 0) || 1
    const axisStep = axisMax <= 60 ? 15 : axisMax <= 120 ? 30 : axisMax <= 360 ? 60 : axisMax <= 720 ? 120 : 180
    const axisTicks: number[] = []
    for (let v = 0; v < axisMax; v += axisStep) axisTicks.push(v)
    // Drop a trailing interior tick that would crowd the peak label.
    if (axisTicks.length > 1 && axisMax - axisTicks[axisTicks.length - 1] < axisStep * 0.5) axisTicks.pop()
    axisTicks.push(axisMax)

    return {
      chartData,
      sports,
      sportColorMap,
      activeDays,
      weekTotal: totals[6] ?? 0,
      prevWeekTotal: prevTotals ? prevTotals[6] : null,
      axisStep,
      axisMax,
      axisTicks,
    }
  }, [data, previous, colorMap])

  if (sports.length === 0) return null

  // The top tick is the peak itself, so it needs an exact label — kept space-free ("2h22")
  // because Recharts word-wraps tick text. Interior steps read as "3h", or minutes below the hour.
  const axisFmt = (v: number) => {
    if (v === 0) return '0'
    if (v !== axisMax) return axisStep % 60 === 0 ? `${v / 60}h` : `${v}m`
    const h = Math.floor(v / 60)
    const m = v % 60
    if (h === 0) return `${m}m`
    return m === 0 ? `${h}h` : `${h}h${m}`
  }

  function makeActiveDot(sport: string, color: string) {
    return (props: unknown) => {
      const { cx, cy, index } = props as { cx: number; cy: number; index: number }
      if (!activeDays[sport]?.has(index)) return <g />
      return <circle cx={cx} cy={cy} r={3} fill={color} fillOpacity={0.8} stroke={isLight ? '#e5e5e5' : '#1a1a1a'} strokeWidth={1} />
    }
  }

  function makeLabel(sport: string, color: string) {
    return (props: unknown) => {
      const { x, y, index } = props as { x: number; y: number; index: number }
      if (!activeDays[sport]?.has(index)) return <g />
      const dayTitles = titles?.[sport]?.[index] ?? []
      if (dayTitles.length === 0) return <g />
      const label = dayTitles.map(t => t.length > 16 ? t.slice(0, 16) + '…' : t).join(', ')
      return (
        <text x={x} y={y - 10} textAnchor="middle" fill={color} fontSize={9} fontFamily="monospace" opacity={0.85}>
          {label}
        </text>
      )
    }
  }

  return (
    <div className="panel p-4">
      <div className="eyebrow mb-1">Accumulated Training Time</div>
      <div className="flex gap-3 mb-3 flex-wrap items-center">
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: totalColor, opacity: 0.5 }} />
          <span className="text-[11px] text-gray-400">Total</span>
          <span className={clsx('text-[11px] font-mono', isLight ? 'text-gray-700' : 'text-gray-200')}>
            {formatDurationHM(weekTotal * 60)}
          </span>
        </div>
        {prevWeekTotal !== null && (
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-[2px]" style={{ backgroundColor: prevColor }} />
            <span className="text-[11px] text-gray-400">Last week</span>
            <span className={clsx('text-[11px] font-mono', isLight ? 'text-gray-600' : 'text-gray-400')}>
              {formatDurationHM(prevWeekTotal * 60)}
            </span>
          </div>
        )}
        {sports.map(s => (
          <div key={s} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: sportColorMap[s] }} />
            <span className="text-[11px] text-gray-400">{s}</span>
          </div>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={chartData} margin={{ top: 20, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
          <XAxis dataKey="day" tick={{ fill: colors.tickFill, fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis
            tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={38}
            domain={[0, axisMax]}
            ticks={axisTicks}
            interval={0}
            tickFormatter={axisFmt}
          />
          <Tooltip
            {...colors.tooltip}
            formatter={(value, name) => [formatDurationHM(Number(value) * 60), String(name)]}
            itemSorter={item => (item.dataKey === '_total' ? 0 : item.dataKey === '_prevTotal' ? 1 : 2)}
          />
          <Line
            type="monotone"
            dataKey="_total"
            name="Total"
            stroke={totalColor}
            strokeOpacity={0.5}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: totalColor, stroke: 'none' }}
          />
          {prevWeekTotal !== null && (
            <Line
              type="monotone"
              dataKey="_prevTotal"
              name="Last week"
              stroke={prevColor}
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              activeDot={{ r: 3, fill: prevColor, stroke: 'none' }}
            />
          )}
          {sports.map(sport => (
            <Area
              key={sport}
              type="monotone"
              dataKey={sport}
              stroke={sportColorMap[sport]}
              strokeOpacity={0.6}
              fill={sportColorMap[sport]}
              fillOpacity={0.08}
              strokeWidth={1.5}
              dot={makeActiveDot(sport, sportColorMap[sport])}
              label={makeLabel(sport, sportColorMap[sport])}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

/** The inspected week's charts: training time, HR zones and the sport split. */
export default function WeekDetailCharts({ current, previous, colorMap, hrZoneBounds }: {
  current: WeeklyReport
  previous: WeeklyReport | null | undefined
  colorMap: Record<string, string>
  hrZoneBounds: HrZoneBound[] | undefined
}) {
  return (
    <div className="space-y-4" style={{ animation: 'fadeIn 300ms ease-out' }}>
      {/* Accumulated Training Time */}
      {current.time_per_sport_per_day_mins && (
        <AccumulatedChart
          data={current.time_per_sport_per_day_mins}
          previous={previous?.time_per_sport_per_day_mins}
          titles={current.activities_titles_per_day_per_sport}
          colorMap={colorMap}
        />
      )}

      {/* HR Zone Distribution */}
      {current.hr_histogram && hrZoneBounds && hrZoneBounds.length >= 5 && (
        <div className="panel p-4">
          <div className="eyebrow mb-3">HR Zone Distribution</div>
          <HrZoneDistributionChart
            histogram={{ minBpm: current.hr_histogram.min_bpm, counts: current.hr_histogram.counts }}
            zones={hrZoneBounds}
            percentages={[1, 2, 3, 4, 5].map(z => current.hr_zone_distribution?.[z] ?? 0)}
          />
        </div>
      )}

      {/* Pie charts */}
      {current.distance_per_sport_km && Object.keys(current.distance_per_sport_km).length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <SportPieChart
            title="Distance"
            data={current.distance_per_sport_km}
            formatValue={(v: number, sport?: string) => formatDist(v, sport)}
            colorMap={colorMap}
          />
          <SportPieChart
            title="Time (min)"
            data={Object.fromEntries(
              Object.entries(current.time_per_sport_hours ?? {}).map(([s, h]) => [s, h * 60])
            )}
            formatValue={(v: number) => `${Math.round(v)} min`}
            colorMap={colorMap}
          />
        </div>
      )}
    </div>
  )
}
