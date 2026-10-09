import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  ResponsiveContainer, ComposedChart, Line, Area, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceArea,
} from 'recharts'
import { useTheme } from '../../hooks/useTheme'
import { useGarminDay, type GarminDay } from '../../api/hooks'
import ChartPanel, { LegendSwatch } from '../shared/ChartPanel'
import { ACCENT, ACCENT_LIGHT, AMBER, MUTED, POS, SLEEP_STAGE_COLORS, fmtDayDate, useGarminChartProps } from './garmin'

const HOUR_MS = 3_600_000
const RIGHT_AXIS_WIDTH = 36

/** Timeline times are local wall-clock ms, so they're read as UTC. */
const clock = (ms: number) => new Date(ms).toISOString().slice(11, 16)

function shiftDay(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

// Samples further apart than this are a gap (watch off, or not measured during exercise)
const GAP_MS = 10 * 60_000

/** Chart points, with a break wherever the watch didn't measure. */
function points(series: [number, number][]): { t: number; v: number | null }[] {
  const out: { t: number; v: number | null }[] = []
  for (const [t, v] of series) {
    const prev = out[out.length - 1]
    if (prev && t - prev.t > GAP_MS) out.push({ t: prev.t + 1, v: null })
    out.push({ t, v })
  }
  return out
}

/** The day's sleep as continuous stretches, for shading the charts. */
function sleepStretches(stages: GarminDay['sleep']): { start: number; end: number }[] {
  const out: { start: number; end: number }[] = []
  for (const s of [...stages].sort((a, b) => a.start - b.start)) {
    const last = out[out.length - 1]
    if (last && s.start <= last.end + 5 * 60_000) last.end = Math.max(last.end, s.end)
    else out.push({ start: s.start, end: s.end })
  }
  return out
}

const STAGE_LABEL = { deep: 'Deep', light: 'Light', rem: 'REM', awake: 'Awake' } as const

/** One day of watch data on a single clock, with the night's sleep and the day's activities. */
export default function DayTimeline({ day, latest, onDayChange }: {
  day: string
  latest: string | null
  onDayChange: (day: string) => void
}) {
  const { colors } = useTheme()
  const { yAxisProps } = useGarminChartProps()
  const { data, isError, isFetching } = useGarminDay(day)

  const view = useMemo(() => {
    if (!data) return null
    return {
      hr: points(data.heart_rate),
      stress: points(data.stress),
      bodyBattery: points(data.body_battery),
      respiration: points(data.respiration),
      spo2: points(data.spo2),
      sleep: sleepStretches(data.sleep),
      ticks: Array.from({ length: 9 }, (_, i) => data.start + i * 3 * HOUR_MS),
    }
  }, [data])

  const atLatest = latest != null && day >= latest
  const toolbar = (
    <div className="flex items-center gap-1">
      <button className="chip" onClick={() => onDayChange(shiftDay(day, -1))} aria-label="Previous day">‹</button>
      <button className="chip" disabled={atLatest} onClick={() => onDayChange(shiftDay(day, 1))} aria-label="Next day">›</button>
      {latest && !atLatest && <button className="chip" onClick={() => onDayChange(latest)}>Latest</button>}
    </div>
  )

  if (isError || !data || !view) {
    return (
      <ChartPanel title="Day timeline" sublabel={fmtDayDate(day)} accent={ACCENT} toolbar={toolbar}>
        <div className="text-xs text-gray-500 py-8 text-center">
          {isError ? 'No intraday watch data for this day.' : 'Loading…'}
        </div>
      </ChartPanel>
    )
  }

  const xAxis = {
    dataKey: 't',
    type: 'number' as const,
    domain: [data.start, data.end],
    ticks: view.ticks,
    tickFormatter: clock,
    tick: { fill: colors.tickFill, fontSize: 10 },
    axisLine: false as const,
    tickLine: false as const,
    allowDataOverflow: true,
  }
  const rightSpacer = <YAxis yAxisId="spacer" orientation="right" width={RIGHT_AXIS_WIDTH} tick={false} axisLine={false} />
  const tooltip = { ...colors.tooltip, labelFormatter: (v: unknown) => clock(Number(v)) }
  const shading = (yAxisId: string) => [
    ...view.sleep.map(s => (
      <ReferenceArea key={`sleep-${s.start}`} yAxisId={yAxisId} x1={s.start} x2={s.end}
        fill={SLEEP_STAGE_COLORS.deep} fillOpacity={0.07} />
    )),
    ...data.activities.map(a => (
      <ReferenceArea key={`activity-${a.id}`} yAxisId={yAxisId} x1={a.start} x2={a.end}
        fill={AMBER} fillOpacity={0.14} />
    )),
  ]
  const margin = { top: 4, right: 4, left: 4, bottom: 0 }

  return (
    <ChartPanel
      title="Day timeline" sublabel={fmtDayDate(day)} accent={ACCENT} toolbar={toolbar}
      legend={<>
        {(['deep', 'light', 'rem', 'awake'] as const).map(s => (
          <LegendSwatch key={s} color={SLEEP_STAGE_COLORS[s]} label={STAGE_LABEL[s]} />
        ))}
        <LegendSwatch color={AMBER} label="Activity" />
      </>}
    >
      <div className={isFetching ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
        {data.activities.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {data.activities.map(a => (
              <Link key={a.id} to={`/activities/${a.id}`} className="chip">
                {clock(a.start)}–{clock(a.end)} · {a.name ?? a.sport_type}
              </Link>
            ))}
          </div>
        )}

        {/* Sleep stages and activities as lanes, inset to line up with the charts' plot area */}
        <div className="space-y-1" style={{ marginLeft: margin.left + yAxisProps.width, marginRight: margin.right + RIGHT_AXIS_WIDTH }}>
          {[
            data.sleep.map(s => ({ key: `s${s.start}`, start: s.start, end: s.end, color: SLEEP_STAGE_COLORS[s.stage], title: STAGE_LABEL[s.stage] })),
            data.activities.map(a => ({ key: `a${a.id}`, start: a.start, end: a.end, color: AMBER, title: a.name ?? '' })),
          ].map((lane, i) => (
            <div key={i} className="relative h-2.5 rounded-sm" style={{ background: colors.gridStroke }}>
              {lane.map(seg => (
                <div key={seg.key} title={`${seg.title} · ${clock(seg.start)}–${clock(seg.end)}`}
                  className="absolute inset-y-0 rounded-sm"
                  style={{
                    left: `${((seg.start - data.start) / (data.end - data.start)) * 100}%`,
                    width: `${Math.max(0.2, ((seg.end - seg.start) / (data.end - data.start)) * 100)}%`,
                    background: seg.color,
                  }} />
              ))}
            </div>
          ))}
        </div>

        <div className="eyebrow mt-3 mb-1 flex gap-3">
          <span>Heart rate</span>
        </div>
        <ResponsiveContainer width="100%" height={150}>
          <ComposedChart data={view.hr} margin={margin}>
            <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
            <XAxis {...xAxis} />
            <YAxis yAxisId="hr" {...yAxisProps} domain={['dataMin - 5', 'dataMax + 5']} />
            {rightSpacer}
            {shading('hr')}
            <Tooltip {...tooltip} formatter={(v: unknown) => [`${v} bpm`, 'HR']} />
            <Line yAxisId="hr" dataKey="v" stroke={ACCENT} strokeWidth={1.5} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>

        <div className="eyebrow mt-3 mb-1 flex flex-wrap gap-3 items-center">
          <span>Stress & body battery</span>
          <LegendSwatch color={AMBER} label="Stress" />
          <LegendSwatch color={POS} label="Body battery" />
        </div>
        <ResponsiveContainer width="100%" height={140}>
          <ComposedChart margin={margin}>
            <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
            <XAxis {...xAxis} />
            <YAxis yAxisId="pct" {...yAxisProps} domain={[0, 100]} />
            {rightSpacer}
            {shading('pct')}
            <Tooltip {...tooltip} formatter={(v: unknown, name) => [`${v}`, name === 'stress' ? 'Stress' : 'Body battery']} />
            <Area yAxisId="pct" data={view.stress} dataKey="v" name="stress" type="stepAfter"
              stroke={AMBER} strokeWidth={1} fill={AMBER} fillOpacity={0.25} isAnimationActive={false} />
            <Line yAxisId="pct" data={view.bodyBattery} dataKey="v" name="body_battery"
              stroke={POS} strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>

        <div className="eyebrow mt-3 mb-1 flex flex-wrap gap-3 items-center">
          <span>Breathing & SpO2</span>
          <LegendSwatch color={ACCENT_LIGHT} label="Breaths/min" />
          <LegendSwatch color={MUTED} label="SpO2 hourly (%)" />
        </div>
        <ResponsiveContainer width="100%" height={120}>
          <ComposedChart margin={margin}>
            <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
            <XAxis {...xAxis} />
            <YAxis yAxisId="resp" {...yAxisProps} domain={['dataMin - 2', 'dataMax + 2']} />
            <YAxis yAxisId="spo2" orientation="right" width={RIGHT_AXIS_WIDTH} domain={[80, 100]}
              tick={{ fill: colors.tickFillSecondary, fontSize: 10 }} axisLine={false} tickLine={false} />
            {shading('resp')}
            <Tooltip {...tooltip} formatter={(v: unknown, name) => name === 'spo2' ? [`${v}%`, 'SpO2'] : [`${v}`, 'Breaths/min']} />
            <Line yAxisId="resp" data={view.respiration} dataKey="v" name="respiration"
              stroke={ACCENT_LIGHT} strokeWidth={1.25} dot={false} isAnimationActive={false} />
            <Line yAxisId="spo2" data={view.spo2} dataKey="v" name="spo2"
              stroke={MUTED} strokeWidth={1} strokeDasharray="3 3"
              dot={{ r: 2, fill: MUTED, stroke: MUTED }} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </ChartPanel>
  )
}
