import { useMemo } from 'react'
import {
  ResponsiveContainer, BarChart, LineChart, Bar, Line, XAxis, YAxis, Tooltip, CartesianGrid,
  ReferenceLine, ReferenceArea,
} from 'recharts'
import { useTheme } from '../../hooks/useTheme'
import type { GarminTrends } from '../../api/hooks'
import ChartPanel, { LegendSwatch } from '../shared/ChartPanel'
import {
  ACCENT, ACCENT_LIGHT, AMBER, NEG, POS, displayNum, dotProps, num, stressZoneColor,
  useGarminChartProps,
} from './garmin'

/** Stress, body battery and overnight SpO2 & respiration. */
export default function StressSection({ trends: t, days }: { trends: GarminTrends | undefined; days: number }) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const { chartMargin, xAxisProps, yAxisProps, tooltipProps } = useGarminChartProps()

  const stressData = useMemo(() => (t?.metrics.stress ?? []).map(r => ({
    date: r.date,
    avg: num(r.avg),
    max: num(r.max),
  })), [t])

  const bbData = useMemo(() => (t?.metrics.body_battery ?? []).map(r => ({
    date: r.date,
    charged: num(r.charged) ?? 0,
    drained: -1 * (num(r.drained) ?? 0),
  })), [t])

  const respSpo2Data = useMemo(() => {
    const sleep = t?.metrics.sleep ?? []
    return sleep.map(r => ({
      date: r.date,
      spo2: num(r.avg_spo2),
      respiration: num(r.avg_respiration),
    }))
  }, [t])

  return (
    <>
      {/* ── Stress + Body battery ────────────────────────────── */}
      <div className="section-head pt-2">
        <span className="eyebrow">Stress & energy</span>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartPanel title="Stress" sublabel={`last ${days}d`} accent={ACCENT}
          legend={<>
            <LegendSwatch color={POS} label="Rest 0–25" />
            <LegendSwatch color={ACCENT} label="Low 26–50" />
            <LegendSwatch color="#f59e0b" label="Medium 51–75" />
            <LegendSwatch color={NEG} label="High 76–100" />
          </>}
        >
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={stressData} margin={chartMargin}>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps} domain={[0, 100]} />
              <Tooltip {...tooltipProps} />
              {/* Garmin stress zones — tinted reference bands */}
              <ReferenceArea y1={0}  y2={25}  fill={POS}     fillOpacity={0.10} />
              <ReferenceArea y1={25} y2={50}  fill={ACCENT}  fillOpacity={0.08} />
              <ReferenceArea y1={50} y2={75}  fill={AMBER}   fillOpacity={0.10} />
              <ReferenceArea y1={75} y2={100} fill={NEG}     fillOpacity={0.12} />
              <Line type="monotone" dataKey="max"
                stroke={isLight ? '#94a3b8' : '#cbd5e1'} strokeOpacity={0.7}
                strokeWidth={1.25} strokeDasharray="4 3"
                dot={false} isAnimationActive={false} name="Peak" />
              <Line type="monotone" dataKey="avg"
                stroke={isLight ? '#475569' : '#cbd5e1'} strokeOpacity={0.55}
                strokeWidth={1.5}
                isAnimationActive={false} name="Avg"
                dot={(props: unknown) => {
                  const dot = dotProps(props)
                  if (!dot) return <g />
                  const v = num(dot.payload.avg)
                  if (v == null) return <g />
                  const c = stressZoneColor(v)
                  return (
                    <circle cx={dot.cx} cy={dot.cy} r={3.5}
                      fill={c} stroke={c} strokeWidth={1.5} />
                  )
                }}
                activeDot={(props: unknown) => {
                  const dot = dotProps(props)
                  const v = num(dot?.payload.avg) ?? 0
                  const c = stressZoneColor(v)
                  return dot ? <circle cx={dot.cx} cy={dot.cy} r={5} fill={c} stroke={c} /> : <g />
                }} />
            </LineChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Body battery" sublabel={`last ${days}d`} accent={ACCENT}
          legend={<>
            <LegendSwatch color={POS} label="Charged" />
            <LegendSwatch color={NEG} label="Drained" />
          </>}
        >
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={bbData} margin={chartMargin}>
              <defs>
                <linearGradient id="bbCharged" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"  stopColor="#34d399" stopOpacity={0.95} />
                  <stop offset="100%" stopColor={POS}   stopOpacity={0.85} />
                </linearGradient>
                <linearGradient id="bbDrained" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"  stopColor={NEG}    stopOpacity={0.85} />
                  <stop offset="100%" stopColor="#fca5a5" stopOpacity={0.95} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps}
                tickFormatter={(v) => v === 0 ? '0' : Math.abs(v).toString()} />
              <Tooltip {...tooltipProps}
                formatter={(v: unknown, name) => [Math.abs(displayNum(v)), name === 'charged' ? 'Charged' : 'Drained']} />
              <ReferenceLine y={0} stroke={colors.tickFillSecondary} strokeOpacity={0.35} />
              <Bar dataKey="charged" fill="url(#bbCharged)" isAnimationActive={false} />
              <Bar dataKey="drained" fill="url(#bbDrained)" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>
      </div>

      {/* ── SpO2 + Respiration overnight ─────────────────────── */}
      <ChartPanel
        title="Overnight SpO2 & respiration" sublabel={`last ${days}d`} accent={ACCENT}
        legend={<>
          <LegendSwatch color={ACCENT} label="SpO2 %" />
          <LegendSwatch color={ACCENT_LIGHT} label="Respiration brpm" variant="dashed" />
        </>}
      >
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={respSpo2Data} margin={chartMargin}>
            <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
            <XAxis {...xAxisProps} />
            <YAxis yAxisId="spo2" {...yAxisProps} domain={[85, 100]}
              tickFormatter={(v) => `${v}%`} />
            <YAxis yAxisId="resp" orientation="right" {...yAxisProps} domain={[8, 22]}
              tickFormatter={(v) => `${v}`} />
            <Tooltip {...tooltipProps}
              formatter={(v: unknown, name) => name === 'spo2'
                ? [`${displayNum(v)}%`, 'SpO2']
                : [`${displayNum(v)} brpm`, 'Respiration']} />
            <Line yAxisId="spo2" type="monotone" dataKey="spo2"
              stroke={ACCENT} strokeWidth={2}
              dot={{ r: 2, fill: ACCENT, stroke: ACCENT }}
              activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
            <Line yAxisId="resp" type="monotone" dataKey="respiration"
              stroke={ACCENT_LIGHT} strokeWidth={1.5} strokeDasharray="4 3"
              dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartPanel>
    </>
  )
}
