import {
  Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { CoachPlan } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { dateToLocalStr, parseLocalDate } from '../../utils/dates'
import { formatClockDuration } from '../../utils/formatSpeed'
import ChartPanel, { LegendSwatch } from '../shared/ChartPanel'
import { fmtDate, useGarminChartProps } from '../garmin/garmin'
import { GARMIN_DARK, GARMIN_LIGHT, GOAL, RUN } from './colors'
import PlanHero from './PlanHero'

/** The plan at a glance: the race as the hero, then km per week and the prediction's trend. */
export default function PlanOverview({ plan }: { plan: CoachPlan }) {
  const { theme } = useTheme()
  const pred = plan.progress.prediction
  return (
    <div className="space-y-10">
      <PlanHero plan={plan} />
      <div className="grid md:grid-cols-2 gap-3">
        <WeeklyKm plan={plan} />
        {pred && (pred.z2.length > 0 || pred.garmin.length > 0) && <PredictionTrend plan={plan} garminColor={theme === 'light' ? GARMIN_LIGHT : GARMIN_DARK} />}
      </div>
    </div>
  )
}

function WeeklyKm({ plan }: { plan: CoachPlan }) {
  const { colors } = useTheme()
  const { chartMargin, yAxisProps, tooltipProps } = useGarminChartProps()
  const data = plan.progress.weeks.map(w => ({ ...w, label: fmtDate(w.week_start) }))
  return (
    <ChartPanel
      title="Km per week"
      glow={false}
      legend={<><LegendSwatch color={RUN} label="Run" /><LegendSwatch color={colors.tickFill} label="Planned" variant="outline" /><LegendSwatch color={colors.tickFill} label="Phase target" variant="dashed" /></>}
    >
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart data={data} margin={chartMargin} barGap={2}>
          <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: colors.tickFill, fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis {...yAxisProps} />
          <Tooltip
            {...tooltipProps}
            labelFormatter={(l: unknown) => `Week of ${l}`}
            formatter={(v: unknown, name: unknown) => [v == null ? '—' : `${v} km`, String(name)]}
          />
          <Bar dataKey="planned_km" name="Planned" fill="none" stroke={colors.tickFill} strokeDasharray="3 2" radius={[4, 4, 0, 0]} maxBarSize={14} isAnimationActive={false} />
          <Bar dataKey="done_km" name="Run" fill={RUN} radius={[4, 4, 0, 0]} maxBarSize={14} isAnimationActive={false} />
          <Line dataKey="target_km" name="Phase target" type="step" stroke={colors.tickFill} strokeDasharray="4 3" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartPanel>
  )
}

function PredictionTrend({ plan, garminColor }: { plan: CoachPlan; garminColor: string }) {
  const { colors } = useTheme()
  const { chartMargin, yAxisProps, tooltipProps } = useGarminChartProps()
  const pred = plan.progress.prediction!
  const toMs = (iso: string) => parseLocalDate(iso).getTime()
  const z2 = pred.z2.map(d => ({ t: toMs(d.date), z2: d.time_s }))
  const garmin = pred.garmin.map(d => ({ t: toMs(d.date), garmin: d.time_s }))
  const values = [...pred.z2, ...pred.garmin].map(d => d.time_s).concat(pred.goal_s != null ? [pred.goal_s] : [])
  if (!values.length) return null
  // Ticks on whole half-minutes (whole minutes over a wide range), so the axis reads as race times
  const step = Math.max(...values) - Math.min(...values) > 240 ? 60 : 30
  const lo = Math.floor((Math.min(...values) - 5) / step) * step
  const hi = Math.ceil((Math.max(...values) + 5) / step) * step
  const ticks = Array.from({ length: Math.round((hi - lo) / step) + 1 }, (_, i) => lo + i * step)
  return (
    <ChartPanel
      title={`${pred.distance} prediction`}
      glow={false}
      legend={<><LegendSwatch color={RUN} label="z2, weekly" /><LegendSwatch color={garminColor} label="Garmin, daily" variant="outline" /><LegendSwatch color={GOAL} label="Goal" variant="dashed" /></>}
    >
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart margin={chartMargin}>
          <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']}
            tickFormatter={(t: number) => fmtDate(dateToLocalStr(new Date(t)))}
            tick={{ fill: colors.tickFill, fontSize: 10 }} axisLine={false} tickLine={false}
          />
          {/* Reversed so faster is up */}
          <YAxis {...yAxisProps} reversed domain={[lo, hi]} ticks={ticks} tickFormatter={(v: number) => formatClockDuration(v)} />
          <Tooltip
            {...tooltipProps}
            labelFormatter={(t: unknown) => fmtDate(dateToLocalStr(new Date(Number(t))))}
            formatter={(v: unknown, name: unknown) => [formatClockDuration(Number(v)), String(name)]}
          />
          {pred.goal_s != null && (
            <ReferenceLine y={pred.goal_s} stroke={GOAL} strokeDasharray="4 3" strokeWidth={1.5}
              label={{ value: `goal ${formatClockDuration(pred.goal_s)}`, position: 'insideTopRight', fill: colors.tickFill, fontSize: 10 }} />
          )}
          <Scatter data={garmin} dataKey="garmin" name="Garmin" fill="none" stroke={garminColor} strokeWidth={1.5} isAnimationActive={false} shape="circle" />
          <Line data={z2} dataKey="z2" name="z2" stroke={RUN} strokeWidth={2} dot={{ r: 3, fill: RUN, strokeWidth: 0 }} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartPanel>
  )
}
