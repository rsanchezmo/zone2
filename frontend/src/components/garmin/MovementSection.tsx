import { useMemo } from 'react'
import clsx from 'clsx'
import {
  ResponsiveContainer, BarChart, LineChart, Bar, Line, Cell, XAxis, YAxis, Tooltip, CartesianGrid,
  ReferenceLine, ReferenceArea,
} from 'recharts'
import { useTheme } from '../../hooks/useTheme'
import type { GarminTrends } from '../../api/hooks'
import ChartPanel, { LegendSwatch } from '../shared/ChartPanel'
import {
  ACCENT, ACCENT_LIGHT, MUTED, POS, VO2, displayNum, dotProps, num, useGarminChartProps,
  vo2ZoneColor,
} from './garmin'

/** Steps, distance, floors, calories, intensity minutes and VO2 max. */
export default function MovementSection({ trends: t, days }: { trends: GarminTrends | undefined; days: number }) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const { chartMargin, xAxisProps, yAxisProps, tooltipProps } = useGarminChartProps()

  const stepsData = useMemo(() => (t?.metrics.daily_steps ?? []).map(r => ({
    date: r.date,
    steps: num(r.total_steps),
    goal: num(r.step_goal),
  })), [t])

  // Reference line uses the most recent known goal (rows are chronological).
  const goalRef = useMemo(() => {
    for (let i = stepsData.length - 1; i >= 0; i--) {
      const g = stepsData[i].goal
      if (g != null) return g
    }
    return null
  }, [stepsData])

  const caloriesData = useMemo(() => (t?.metrics.user_summary ?? []).map(r => ({
    date: r.date,
    active: num(r.active_kcal) ?? 0,
    bmr: num(r.bmr_kcal) ?? 0,
  })), [t])

  const imData = useMemo(() => (t?.metrics.intensity_minutes ?? []).map(r => ({
    date: r.date,
    moderate: num(r.moderate) ?? 0,
    vigorous: num(r.vigorous) ?? 0,
  })), [t])

  const distanceData = useMemo(() => (t?.metrics.daily_steps ?? []).map(r => {
    const m = num(r.total_distance_m)
    return { date: r.date, km: m != null ? m / 1000 : null }
  }), [t])

  const floorsData = useMemo(() => (t?.metrics.user_summary ?? []).map(r => ({
    date: r.date,
    floors: num(r.floors_climbed),
  })), [t])

  const vo2Data = useMemo(() => (t?.metrics.training_status ?? [])
    .map(r => ({ date: r.date, vo2max: num(r.vo2max) }))
    .filter(r => r.vo2max !== null), [t])

  return (
    <>
      {/* ── Steps ─────────────────────────────────────────────── */}
      <div className="section-head pt-2">
        <span className="eyebrow">Movement</span>
      </div>
      <ChartPanel
        title="Daily steps" sublabel={`last ${days}d`} accent={ACCENT}
        legend={<>
          <LegendSwatch color={ACCENT} label="Below goal" />
          <LegendSwatch color={POS} label="Goal met" />
          {goalRef != null && <LegendSwatch color={MUTED} label={`Goal · ${goalRef.toLocaleString()}`} variant="dashed" />}
        </>}
      >
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={stepsData} margin={chartMargin}>
            <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
            <XAxis {...xAxisProps} />
            <YAxis {...yAxisProps}
              tickFormatter={(v) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)} />
            <Tooltip {...tooltipProps} formatter={(v: unknown) => displayNum(v).toLocaleString()} />
            {goalRef != null && (
              <ReferenceLine y={goalRef} stroke={MUTED} strokeOpacity={0.5} strokeDasharray="4 3" />
            )}
            <Bar dataKey="steps" isAnimationActive={false}>
              {stepsData.map((entry, i) => (
                <Cell key={i}
                  fill={entry.steps != null && entry.goal != null && entry.steps >= entry.goal ? POS : ACCENT} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartPanel>

      {/* ── Distance + Floors + Calories ─────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartPanel title="Distance walked" sublabel={`last ${days}d`} accent={ACCENT}
          legend={<LegendSwatch color={ACCENT} label="km / day" />}
        >
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={distanceData} margin={chartMargin}>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps} tickFormatter={(v) => `${v}`} />
              <Tooltip {...tooltipProps}
                formatter={(v: unknown) => [`${displayNum(v).toFixed(2)} km`, 'Distance']} />
              <Bar dataKey="km" fill={ACCENT} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Floors climbed" sublabel={`last ${days}d`} accent={ACCENT}
          legend={<LegendSwatch color={ACCENT} label="floors / day" />}
        >
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={floorsData} margin={chartMargin}>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps} tickFormatter={(v) => `${Math.round(v)}`} />
              <Tooltip {...tooltipProps}
                formatter={(v: unknown) => [`${Math.round(displayNum(v))} floors`, 'Climbed']} />
              <Bar dataKey="floors" fill={ACCENT} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Calories" sublabel={`last ${days}d`} accent={ACCENT}
          legend={<>
            <LegendSwatch color="#64748b" label="BMR · resting" />
            <LegendSwatch color={POS} label="Active · earned" />
          </>}
        >
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={caloriesData} margin={chartMargin}>
              <defs>
                <linearGradient id="kcalBmr" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"  stopColor="#94a3b8" stopOpacity={0.85} />
                  <stop offset="100%" stopColor="#475569" stopOpacity={0.7} />
                </linearGradient>
                <linearGradient id="kcalActive" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"  stopColor="#34d399" stopOpacity={0.95} />
                  <stop offset="100%" stopColor={POS}   stopOpacity={0.85} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps} tickFormatter={(v) => v >= 1000 ? `${(v/1000).toFixed(1)}k` : `${v}`} />
              <Tooltip {...tooltipProps}
                formatter={(v: unknown, name) => [`${Math.round(displayNum(v)).toLocaleString()} kcal`, name === 'bmr' ? 'BMR' : 'Active']} />
              <Bar dataKey="bmr" stackId="kcal" fill="url(#kcalBmr)" isAnimationActive={false} />
              <Bar dataKey="active" stackId="kcal" fill="url(#kcalActive)" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>
      </div>

      {/* ── Intensity minutes ────────────────────────────────── */}
      <ChartPanel
        title="Intensity minutes" sublabel={`last ${days}d`} accent={ACCENT}
        legend={<>
          <LegendSwatch color={ACCENT} label="Vigorous" />
          <LegendSwatch color={ACCENT_LIGHT} label="Moderate" />
        </>}
      >
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={imData} margin={chartMargin}>
            <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
            <XAxis {...xAxisProps} />
            <YAxis {...yAxisProps} tickFormatter={(v) => `${v}`} />
            <Tooltip {...tooltipProps}
              formatter={(v: unknown, name) => [`${displayNum(v)} min`, name === 'vigorous' ? 'Vigorous' : 'Moderate']} />
            <Bar dataKey="moderate" stackId="im" fill={ACCENT_LIGHT} isAnimationActive={false} />
            <Bar dataKey="vigorous" stackId="im" fill={ACCENT} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </ChartPanel>

      {/* ── VO2 max (full width) ─────────────────────────────── */}
      <ChartPanel title="VO2 max" sublabel={`last ${days}d`} accent={ACCENT}
        legend={<>
          <LegendSwatch color={VO2.superior}  label="Superior ≥55" />
          <LegendSwatch color={VO2.excellent} label="Excellent 49–55" />
          <LegendSwatch color={VO2.good}      label="Good 44–49" />
          <LegendSwatch color={VO2.fair}      label="Fair 39–44" />
          <LegendSwatch color={VO2.poor}      label="Poor <39" />
        </>}
      >
        {vo2Data.length === 0 ? (
          <div className={clsx('flex items-center justify-center h-[220px] text-xs', isLight ? 'text-gray-400' : 'text-gray-500')}>
            No VO2 max updates in this window
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={vo2Data} margin={chartMargin}>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              {/* Pad the y-domain so the relevant zone bands sit visible
                  regardless of tight measured-value variation. */}
              <YAxis {...yAxisProps} domain={[
                (min: number) => Math.min(min - 1, 39),
                (max: number) => Math.max(max + 1, 60),
              ]} />
              <Tooltip {...tooltipProps}
                formatter={(v: unknown) => `${displayNum(v).toFixed(1)} ml/kg/min`} />
              <ReferenceArea y1={0}  y2={39} fill={VO2.poor}      fillOpacity={0.10} />
              <ReferenceArea y1={39} y2={44} fill={VO2.fair}      fillOpacity={0.10} />
              <ReferenceArea y1={44} y2={49} fill={VO2.good}      fillOpacity={0.08} />
              <ReferenceArea y1={49} y2={55} fill={VO2.excellent} fillOpacity={0.10} />
              <ReferenceArea y1={55} y2={99} fill={VO2.superior}  fillOpacity={0.12} />
              <Line type="monotone" dataKey="vo2max"
                stroke={isLight ? '#475569' : '#cbd5e1'} strokeOpacity={0.55}
                strokeWidth={1.5}
                isAnimationActive={false}
                dot={(props: unknown) => {
                  const dot = dotProps(props)
                  if (!dot) return <g />
                  const v = num(dot.payload.vo2max)
                  if (v == null) return <g />
                  const c = vo2ZoneColor(v)
                  return <circle cx={dot.cx} cy={dot.cy} r={3.5}
                    fill={c} stroke={c} strokeWidth={1.5} />
                }}
                activeDot={(props: unknown) => {
                  const dot = dotProps(props)
                  const v = num(dot?.payload.vo2max) ?? 0
                  const c = vo2ZoneColor(v)
                  return dot ? <circle cx={dot.cx} cy={dot.cy} r={5} fill={c} stroke={c} /> : <g />
                }} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </ChartPanel>
    </>
  )
}
