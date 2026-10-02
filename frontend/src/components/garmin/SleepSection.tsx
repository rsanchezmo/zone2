import { useMemo } from 'react'
import {
  ResponsiveContainer, ComposedChart, LineChart, AreaChart, Bar, Line, Area, XAxis, YAxis, Tooltip,
  CartesianGrid,
} from 'recharts'
import { useTheme } from '../../hooks/useTheme'
import type { GarminTrends } from '../../api/hooks'
import ChartPanel, { LegendSwatch } from '../shared/ChartPanel'
import {
  ACCENT, ACCENT_LIGHT, displayNum, hrvTone, num, secondsToMinutes, toneColor,
  useGarminChartProps, type GarminCard,
} from './garmin'

/** Sleep stages, heart rate and HRV overnight. */
export default function SleepSection({ trends: t, days, card }: { trends: GarminTrends | undefined; days: number; card: GarminCard }) {
  const { colors } = useTheme()
  const { chartMargin, xAxisProps, yAxisProps, tooltipProps } = useGarminChartProps()

  const sleepData = useMemo(() => (t?.metrics.sleep ?? []).map(r => ({
    date: r.date,
    deep:  secondsToMinutes(r.deep_seconds),
    rem:   secondsToMinutes(r.rem_seconds),
    light: secondsToMinutes(r.light_seconds),
    awake: secondsToMinutes(r.awake_seconds),
    score: num(r.score),
    sleep_hr: num(r.avg_hr),
  })), [t])

  const hrData = useMemo(() => (t?.metrics.heart_rates ?? []).map(r => ({
    date: r.date,
    resting: num(r.resting),
    min: num(r.min),
    max: num(r.max),
  })), [t])

  const hrvData = useMemo(() => (t?.metrics.hrv ?? []).map(r => ({
    date: r.date,
    last_night: num(r.last_night_avg),
    weekly: num(r.weekly_avg),
  })), [t])

  return (
    <>
      <div className="section-head pt-2">
        <span className="eyebrow">Sleep & overnight</span>
      </div>

      {/* ── Sleep stages + score line overlay ───────────────── */}
      {(() => {
        // Single hue per stage, with a vertical opacity fade — saturated
        // at the top edge, dropping toward transparent at the bottom.
        // Mirrors the atmospheric "area-chart fade" look used by the HR
        // panel below.
        const STAGE = {
          deep:  '#6366f1',  // indigo-500
          rem:   '#a855f7',  // purple-500
          light: '#22d3ee',  // cyan-400
          awake: '#94a3b8',  // slate-400
        }
        const grad = (id: string, color: string) => (
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"  stopColor={color} stopOpacity={0.95} />
            <stop offset="100%" stopColor={color} stopOpacity={0.08} />
          </linearGradient>
        )
        return (
          <ChartPanel
            title="Sleep stages & score" sublabel={`last ${days}d`} accent={ACCENT}
            legend={<>
              <LegendSwatch color={STAGE.deep}  label="Deep" />
              <LegendSwatch color={STAGE.rem}   label="REM" />
              <LegendSwatch color={STAGE.light} label="Light" />
              <LegendSwatch color={STAGE.awake} label="Awake" />
              <LegendSwatch color="#fef08a" label="Sleep score" variant="dashed" />
            </>}
          >
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={sleepData} margin={chartMargin}>
                <defs>
                  {grad('sleepDeep',  STAGE.deep)}
                  {grad('sleepRem',   STAGE.rem)}
                  {grad('sleepLight', STAGE.light)}
                  {grad('sleepAwake', STAGE.awake)}
                </defs>
                <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                <XAxis {...xAxisProps} />
                <YAxis yAxisId="dur" {...yAxisProps} tickFormatter={(v) => `${Math.round(v / 60)}h`} />
                <YAxis yAxisId="score" orientation="right" {...yAxisProps} domain={[0, 100]}
                  tickFormatter={(v) => `${v}`} />
                <Tooltip {...tooltipProps}
                  formatter={(v: unknown, name) => name === 'score'
                    ? [`${displayNum(v)}/100`, 'Score']
                    : [`${Math.round(displayNum(v))} min`, name]} />
                <Bar yAxisId="dur" dataKey="deep"  stackId="s"
                  fill="url(#sleepDeep)" stroke="none"
                  isAnimationActive={false} />
                <Bar yAxisId="dur" dataKey="rem"   stackId="s"
                  fill="url(#sleepRem)" stroke="none"
                  isAnimationActive={false} />
                <Bar yAxisId="dur" dataKey="light" stackId="s"
                  fill="url(#sleepLight)" stroke="none"
                  isAnimationActive={false} />
                <Bar yAxisId="dur" dataKey="awake" stackId="s"
                  fill="url(#sleepAwake)" stroke="none"
                  isAnimationActive={false} />
                <Line yAxisId="score" type="monotone" dataKey="score"
                  stroke="#fef08a" strokeWidth={1.75} strokeDasharray="4 3"
                  dot={{ r: 2.5, fill: '#fef08a', stroke: '#fef08a' }}
                  activeDot={{ r: 4, fill: '#fef08a' }}
                  isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </ChartPanel>
        )
      })()}

      {/* ── HR split: Resting & Min (tight) · Max (fade area) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartPanel
          title="Resting & min HR" sublabel={`last ${days}d`} accent={ACCENT}
          legend={<>
            <LegendSwatch color={ACCENT} label="Resting" />
            <LegendSwatch color={ACCENT_LIGHT} label="Daily min" variant="dashed" />
          </>}
        >
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={hrData} margin={chartMargin}>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps} domain={['dataMin - 3', 'dataMax + 3']} />
              <Tooltip {...tooltipProps}
                formatter={(v: unknown, name) => [`${displayNum(v)} bpm`, name === 'resting' ? 'Resting' : 'Min']} />
              <Line type="monotone" dataKey="min"
                stroke={ACCENT_LIGHT} strokeWidth={1.5} strokeDasharray="4 3"
                dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="resting"
                stroke={ACCENT} strokeWidth={2}
                dot={{ r: 2.5, fill: ACCENT, stroke: ACCENT }}
                activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel
          title="Max HR" sublabel={`last ${days}d`} accent={ACCENT}
          legend={<LegendSwatch color={ACCENT} label="Daily peak" />}
        >
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={hrData} margin={chartMargin}>
              <defs>
                <linearGradient id="hrMax" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"  stopColor={ACCENT} stopOpacity={0.55} />
                  <stop offset="100%" stopColor={ACCENT} stopOpacity={0.04} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps} domain={['dataMin - 5', 'dataMax + 5']} />
              <Tooltip {...tooltipProps}
                formatter={(v: unknown) => [`${displayNum(v)} bpm`, 'Max']} />
              <Area type="monotone" dataKey="max"
                stroke={ACCENT} strokeWidth={2}
                fill="url(#hrMax)"
                activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartPanel>
      </div>

      {/* ── HRV + Sleep HR side-by-side ──────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartPanel
          title="HRV overnight" sublabel={`last ${days}d`} accent={ACCENT}
          status={card.hrvStatus ? (() => {
            const c = toneColor(hrvTone(card.hrvStatus))
            return (
              <span className="inline-flex items-center gap-1.5 text-[10px] uppercase font-semibold tracking-[0.15em] px-2 py-0.5 rounded-full border"
                style={{ background: `${c}1a`, color: c, borderColor: `${c}55` }}>
                <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: c }} />
                {card.hrvStatus.toLowerCase()}
              </span>
            )
          })() : undefined}
          legend={<>
            <LegendSwatch color={ACCENT} label="Last night" />
            <LegendSwatch color={ACCENT_LIGHT} label="7-day avg" variant="dashed" />
          </>}
        >
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={hrvData} margin={chartMargin}>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps} domain={['dataMin - 3', 'dataMax + 3']} />
              <Tooltip {...tooltipProps} formatter={(v: unknown) => `${displayNum(v)} ms`} />
              <Line type="monotone" dataKey="weekly"
                stroke={ACCENT_LIGHT} strokeWidth={1.5} strokeDasharray="4 3"
                dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="last_night"
                stroke={ACCENT} strokeWidth={2}
                dot={{ r: 2.5, fill: ACCENT, stroke: ACCENT }}
                activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel
          title="Avg HR during sleep" sublabel={`last ${days}d`} accent={ACCENT}
          legend={<LegendSwatch color={ACCENT} label="Sleep HR" />}
        >
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={sleepData} margin={chartMargin}>
              <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps} domain={['dataMin - 3', 'dataMax + 3']}
                tickFormatter={(v) => `${Math.round(v)}`} />
              <Tooltip {...tooltipProps} formatter={(v: unknown) => `${displayNum(v)} bpm`} />
              <Line type="monotone" dataKey="sleep_hr"
                stroke={ACCENT} strokeWidth={2}
                dot={{ r: 2.5, fill: ACCENT, stroke: ACCENT }}
                activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartPanel>
      </div>
    </>
  )
}
