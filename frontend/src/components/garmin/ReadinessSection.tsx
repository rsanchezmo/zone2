import { useMemo } from 'react'
import clsx from 'clsx'
import {
  ResponsiveContainer, BarChart, LineChart, Bar, Line, Cell, XAxis, YAxis, Tooltip, CartesianGrid,
  ReferenceArea,
} from 'recharts'
import { useTheme } from '../../hooks/useTheme'
import type { GarminTrends } from '../../api/hooks'
import ChartPanel, { LegendSwatch } from '../shared/ChartPanel'
import {
  ACCENT, AMBER, NEG, POS, acwrZoneColor, displayNum, dotProps, num, readinessZoneColor,
  recoveryZoneColor, useGarminChartProps, type GarminCard,
} from './garmin'
import { FactorBars, LoadBalanceBars } from './GarminTiles'

/** Readiness factors, training readiness, ACWR, recovery time and monthly load. */
export default function ReadinessSection({ trends: t, days, card }: { trends: GarminTrends | undefined; days: number; card: GarminCard }) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const { chartMargin, xAxisProps, yAxisProps, tooltipProps } = useGarminChartProps()

  const recoveryData = useMemo(() => (t?.metrics.training_readiness ?? []).map(r => {
    const recoveryMins = num(r.recovery_time_min)
    return { date: r.date, recovery_h: recoveryMins != null ? recoveryMins / 60 : null }
  }), [t])

  const acwrData = useMemo(() => (t?.metrics.training_status ?? [])
    .map(r => ({ date: r.date, ratio: num(r.acwr_ratio) }))
    .filter(r => r.ratio !== null), [t])

  const readinessData = useMemo(() => (t?.metrics.training_readiness ?? []).map(r => ({
    date: r.date,
    score: num(r.score),
  })), [t])

  return (
    <>
      {/* ── Readiness factor breakdown (today snapshot) ──────────── */}
      <div className="section-head pt-2">
        <span className="eyebrow">Readiness & load</span>
      </div>

      {card.readinessFactors.length > 0 && (
        <ChartPanel
          title="Readiness factors"
          sublabel="today · contributors to your readiness score"
          accent={ACCENT}
        >
          <FactorBars factors={card.readinessFactors} isLight={isLight} />
        </ChartPanel>
      )}

      {/* ── Training readiness (full width) ─────────────────── */}
      <ChartPanel
        title="Training readiness"
        sublabel={`last ${days}d`}
        accent={ACCENT}
        legend={<>
          <LegendSwatch color={POS}    label="High ≥75" />
          <LegendSwatch color={ACCENT} label="Moderate 50–75" />
          <LegendSwatch color={AMBER}  label="Low 25–50" />
          <LegendSwatch color={NEG}    label="Poor <25" />
        </>}
      >
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={readinessData} margin={chartMargin}>
                <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                <XAxis {...xAxisProps} />
                <YAxis {...yAxisProps} domain={[0, 100]} />
                <Tooltip {...tooltipProps} formatter={(v: unknown) => [`${displayNum(v)}/100`, 'Readiness']} />
                <ReferenceArea y1={0}  y2={25}  fill={NEG}    fillOpacity={0.10} />
                <ReferenceArea y1={25} y2={50}  fill={AMBER}  fillOpacity={0.08} />
                <ReferenceArea y1={50} y2={75}  fill={ACCENT} fillOpacity={0.06} />
                <ReferenceArea y1={75} y2={100} fill={POS}    fillOpacity={0.10} />
                <Line type="monotone" dataKey="score"
                  stroke={isLight ? '#475569' : '#cbd5e1'} strokeOpacity={0.55}
                  strokeWidth={1.5}
                  isAnimationActive={false}
                  dot={(props: unknown) => {
                    const dot = dotProps(props)
                    if (!dot) return <g />
                    const v = num(dot.payload.score)
                    if (v == null) return <g />
                    const c = readinessZoneColor(v)
                    return <circle cx={dot.cx} cy={dot.cy} r={3.5}
                      fill={c} stroke={c} strokeWidth={1.5} />
                  }}
                  activeDot={(props: unknown) => {
                    const dot = dotProps(props)
                    const v = num(dot?.payload.score) ?? 0
                    const c = readinessZoneColor(v)
                    return dot ? <circle cx={dot.cx} cy={dot.cy} r={5} fill={c} stroke={c} /> : <g />
                  }} />
              </LineChart>
            </ResponsiveContainer>
          </ChartPanel>

      {/* ── ACWR + Recovery time ─────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartPanel
          title="ACWR (acute / chronic load)" sublabel={`last ${days}d`} accent={ACCENT}
          legend={<>
            <LegendSwatch color={POS}    label="Sweet 0.8–1.3" />
            <LegendSwatch color={AMBER}  label="Caution" />
            <LegendSwatch color={NEG}    label="Risk" />
          </>}
        >
          {acwrData.length === 0 ? (
            <div className={clsx('flex items-center justify-center h-[200px] text-xs', isLight ? 'text-gray-400' : 'text-gray-500')}>
              No ACWR readings in this window
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={acwrData} margin={chartMargin}>
                <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                <XAxis {...xAxisProps} />
                <YAxis {...yAxisProps} domain={[0, 'dataMax + 0.3']}
                  tickFormatter={(v) => v.toFixed(1)} />
                <Tooltip {...tooltipProps}
                  formatter={(v: unknown) => [displayNum(v).toFixed(2), 'ACWR']} />
                {/* ACWR risk bands */}
                <ReferenceArea y1={0}    y2={0.5} fill={NEG}   fillOpacity={0.10} />
                <ReferenceArea y1={0.5}  y2={0.8} fill={AMBER} fillOpacity={0.08} />
                <ReferenceArea y1={0.8}  y2={1.3} fill={POS}   fillOpacity={0.10} />
                <ReferenceArea y1={1.3}  y2={1.5} fill={AMBER} fillOpacity={0.08} />
                <ReferenceArea y1={1.5}  y2={99}  fill={NEG}   fillOpacity={0.12} />
                <Line type="monotone" dataKey="ratio"
                  stroke={isLight ? '#475569' : '#cbd5e1'} strokeOpacity={0.55}
                  strokeWidth={1.5}
                  isAnimationActive={false}
                  dot={(props: unknown) => {
                    const dot = dotProps(props)
                    if (!dot) return <g />
                    const v = num(dot.payload.ratio)
                    if (v == null) return <g />
                    const c = acwrZoneColor(v)
                    return <circle cx={dot.cx} cy={dot.cy} r={3.5}
                      fill={c} stroke={c} strokeWidth={1.5} />
                  }}
                  activeDot={(props: unknown) => {
                    const dot = dotProps(props)
                    const v = num(dot?.payload.ratio) ?? 0
                    const c = acwrZoneColor(v)
                    return dot ? <circle cx={dot.cx} cy={dot.cy} r={5} fill={c} stroke={c} /> : <g />
                  }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </ChartPanel>

        <ChartPanel
          title="Recovery time needed" sublabel={`last ${days}d`} accent={ACCENT}
          legend={<>
            <LegendSwatch color={POS}    label="≤12h" />
            <LegendSwatch color={ACCENT} label="12–24h" />
            <LegendSwatch color={AMBER}  label="24–48h" />
            <LegendSwatch color={NEG}    label=">48h" />
          </>}
        >
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={recoveryData} margin={chartMargin}>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps} tickFormatter={(v) => `${Math.round(v)}h`} />
              <Tooltip {...tooltipProps}
                formatter={(v: unknown) => [`${displayNum(v).toFixed(1)}h`, 'Recovery time']} />
              <ReferenceArea y1={0}  y2={12} fill={POS}    fillOpacity={0.08} />
              <ReferenceArea y1={12} y2={24} fill={ACCENT} fillOpacity={0.06} />
              <ReferenceArea y1={24} y2={48} fill={AMBER}  fillOpacity={0.08} />
              <ReferenceArea y1={48} y2={9999} fill={NEG}  fillOpacity={0.10} />
              <Bar dataKey="recovery_h" isAnimationActive={false}>
                {recoveryData.map((entry, i) => (
                  <Cell key={i} fill={entry.recovery_h != null ? recoveryZoneColor(entry.recovery_h) : ACCENT} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>
      </div>

      {/* ── Monthly training load (full width, own line) ─────── */}
      <ChartPanel
        title="Monthly training load"
        sublabel={card.load?.feedback || 'current month'}
        accent={ACCENT}
      >
        <div className="min-h-[220px]">
          <LoadBalanceBars load={card.load} isLight={isLight} />
        </div>
      </ChartPanel>
    </>
  )
}
