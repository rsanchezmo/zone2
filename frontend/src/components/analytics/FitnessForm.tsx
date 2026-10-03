import { useMemo, useState } from 'react'
import clsx from 'clsx'
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, CartesianGrid,
  ReferenceLine, ReferenceArea,
} from 'recharts'
import { useFitnessForm, type FitnessDay } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { useIsMobile } from '../../hooks/useIsMobile'
import { parseLocalDate, todayLocalStr } from '../../utils/dates'
import StatCard from '../shared/StatCard'
import ChartPanel, { LegendSwatch } from '../shared/ChartPanel'

const RANGES = [
  { label: '3M', days: 90 },
  { label: '6M', days: 180 },
  { label: '1Y', days: 365 },
] as const

const FITNESS = '#60a5fa'
const FATIGUE = '#f472b6'
const LOAD = '#9ca3af'
const RACE = '#eab308'

// Form as a share of fitness. The usual form zones apply to it whatever the
// load scale, which matters because z2's load is TRIMP, not TSS.
const FORM_ZONES = [
  { from: 20, to: 60, label: 'Transition', hint: 'fitness is fading', color: '#f59e0b' },
  { from: 5, to: 20, label: 'Fresh', hint: 'ready to race', color: '#38bdf8' },
  { from: -10, to: 5, label: 'Neutral', hint: 'holding steady', color: '#9ca3af' },
  { from: -30, to: -10, label: 'Optimal', hint: 'building fitness', color: '#22c55e' },
  { from: -80, to: -30, label: 'Overreaching', hint: 'time to back off', color: '#ef4444' },
] as const
const FORM_DOMAIN: [number, number] = [-80, 60]

function formZone(pct: number) {
  return FORM_ZONES.find(z => pct >= z.from) ?? FORM_ZONES[FORM_ZONES.length - 1]
}

function shortDate(iso: string): string {
  return parseLocalDate(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

interface Row {
  date: string
  load: number | null
  plannedLoad: number | null
  fitness: number | null
  fatigue: number | null
  form: number | null
  fitnessPlan: number | null
  fatiguePlan: number | null
  formPlan: number | null
  garminAcute: number | null
  garminChronic: number | null
}

/** Fitness, fatigue and form from daily training load, with the planned
 *  sessions ahead as a dashed projection and races marked. All sports. */
export default function FitnessForm() {
  const { colors } = useTheme()
  const isMobile = useIsMobile()
  const [days, setDays] = useState<number>(180)
  const [showGarmin, setShowGarmin] = useState(false)
  const { data, isLoading } = useFitnessForm(days)

  const series = useMemo(() => data?.series ?? [], [data])
  const rows = useMemo<Row[]>(() => {
    const garmin = new Map((data?.garmin ?? []).map(g => [g.date, g]))
    return series.map((d: FitnessDay, i: number) => {
      // The last logged day also starts the dashed line, so the two join up
      const bridge = !d.projected && series[i + 1]?.projected === true
      const planned = d.projected || bridge
      return {
        date: d.date,
        load: d.projected ? null : d.load,
        plannedLoad: d.projected ? d.load : null,
        fitness: d.projected ? null : d.fitness,
        fatigue: d.projected ? null : d.fatigue,
        form: d.projected ? null : d.form_pct,
        fitnessPlan: planned ? d.fitness : null,
        fatiguePlan: planned ? d.fatigue : null,
        formPlan: planned ? d.form_pct : null,
        garminAcute: garmin.get(d.date)?.acute ?? null,
        garminChronic: garmin.get(d.date)?.chronic ?? null,
      }
    })
  }, [series, data])

  const now = useMemo(() => [...series].reverse().find(d => !d.projected), [series])
  const planEnd = series.at(-1)?.projected ? series.at(-1) : undefined
  const today = todayLocalStr()
  const races = data?.races ?? []
  // The next race inside the projection: the plan reaches it, so its form is known
  const raceAhead = races.find(r => r.date >= today && series.some(d => d.date === r.date))
  const raceDay = raceAhead ? series.find(d => d.date === raceAhead.date) : undefined
  const hasGarmin = (data?.garmin.length ?? 0) > 0

  const xAxis = {
    dataKey: 'date',
    tick: { fill: colors.tickFill, fontSize: 10 },
    tickFormatter: shortDate,
    minTickGap: 28,
    axisLine: false,
    tickLine: false,
  } as const
  const tooltipLabel = (v: unknown) => parseLocalDate(String(v)).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
  const raceLines = (labelled: boolean) => races.map(r => (
    <ReferenceLine key={r.date} x={r.date} stroke={RACE} strokeDasharray="2 3"
      label={labelled ? { value: r.name.length > 16 ? `${r.name.slice(0, 15)}…` : r.name, position: 'insideTopLeft', fill: RACE, fontSize: 9 } : undefined} />
  ))

  if (isLoading || !data) {
    return <div className="h-[420px] panel animate-pulse" />
  }
  if (series.length === 0 || !now) {
    return (
      <div className="panel p-6 text-sm text-gray-500">
        No heart-rate data yet: fitness and form come from activities recorded with heart rate.
      </div>
    )
  }

  const nowPct = now.form_pct ?? 0
  const nowZone = formZone(nowPct)
  const raceZone = raceDay?.form_pct != null ? formZone(raceDay.form_pct) : undefined
  const endZone = planEnd?.form_pct != null ? formZone(planEnd.form_pct) : undefined

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="section-head flex-1">
          <span className="eyebrow">Fitness & form</span>
          <span className="text-[11px] text-gray-500 normal-case tracking-normal">all sports</span>
        </div>
        <div className="flex items-center gap-0.5">
          {RANGES.map(r => (
            <button key={r.days} className="chip font-mono" data-active={days === r.days} onClick={() => setDays(r.days)}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Fitness" value={Math.round(now.fitness)} sublabel={`${data.fitness_days ?? 42}-day load`} accent={FITNESS} />
        <StatCard label="Fatigue" value={Math.round(now.fatigue)} sublabel={`${data.fatigue_days ?? 7}-day load`} accent={FATIGUE} />
        <StatCard label="Form" value={`${nowPct > 0 ? '+' : ''}${Math.round(nowPct)}%`}
          sublabel={`${nowZone.label} · ${nowZone.hint}`} accent={nowZone.color} />
        {raceAhead && raceDay?.form_pct != null && raceZone ? (
          <StatCard label={`Race day · ${shortDate(raceAhead.date)}`} value={`${raceDay.form_pct > 0 ? '+' : ''}${Math.round(raceDay.form_pct)}%`}
            sublabel={`${raceAhead.name} · ${raceZone.label}`} accent={raceZone.color} />
        ) : planEnd?.form_pct != null && endZone ? (
          <StatCard label={`End of plan · ${shortDate(planEnd.date)}`} value={`${planEnd.form_pct > 0 ? '+' : ''}${Math.round(planEnd.form_pct)}%`}
            sublabel={`${endZone.label} if you train as planned`} accent={endZone.color} />
        ) : (
          <StatCard label="Ahead" value="–" sublabel="Plan sessions to see where form is heading" />
        )}
      </div>

      <ChartPanel
        title="Fitness & fatigue" glow={false}
        legend={<>
          <LegendSwatch color={FITNESS} label="Fitness" />
          <LegendSwatch color={FATIGUE} label="Fatigue" />
          <LegendSwatch color={LOAD} label="Daily load" />
          {planEnd && <LegendSwatch color={FITNESS} label="Planned" variant="dashed" />}
          {showGarmin && <LegendSwatch color={FITNESS} label="Garmin acute / chronic" variant="dashed" />}
        </>}
        toolbar={hasGarmin ? (
          <button className="chip" data-active={showGarmin} aria-pressed={showGarmin} onClick={() => setShowGarmin(v => !v)}>
            Garmin load
          </button>
        ) : undefined}
      >
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={rows} margin={{ top: 12, right: 4, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
            <XAxis {...xAxis} />
            <YAxis tick={{ fill: colors.tickFillSecondary, fontSize: 10 }} width={isMobile ? 28 : 36} axisLine={false} tickLine={false} allowDecimals={false} />
            {/* Load bars stay in the lower part, under the curves */}
            <YAxis yAxisId="load" orientation="right" hide domain={[0, (max: number) => max * 2.2]} />
            <YAxis yAxisId="garmin" orientation="right" hide />
            <Tooltip {...colors.tooltip} labelFormatter={tooltipLabel}
              formatter={(v: unknown, name) => [v == null ? '–' : Math.round(Number(v)), name]} />
            <Bar yAxisId="load" stackId="load" dataKey="load" name="Load" fill={LOAD} fillOpacity={0.45} isAnimationActive={false} />
            <Bar yAxisId="load" stackId="load" dataKey="plannedLoad" name="Planned load" fill={LOAD} fillOpacity={0.2} isAnimationActive={false} />
            <Line dataKey="fitness" name="Fitness" stroke={FITNESS} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="fatigue" name="Fatigue" stroke={FATIGUE} strokeWidth={1.5} dot={false} isAnimationActive={false} />
            <Line dataKey="fitnessPlan" name="Fitness (planned)" stroke={FITNESS} strokeWidth={2} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            <Line dataKey="fatiguePlan" name="Fatigue (planned)" stroke={FATIGUE} strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            {showGarmin && <Line yAxisId="garmin" dataKey="garminChronic" name="Garmin chronic" stroke={FITNESS} strokeOpacity={0.9} strokeWidth={1.5} strokeDasharray="1 3" dot={false} isAnimationActive={false} connectNulls />}
            {showGarmin && <Line yAxisId="garmin" dataKey="garminAcute" name="Garmin acute" stroke={FATIGUE} strokeOpacity={0.9} strokeWidth={1.5} strokeDasharray="1 3" dot={false} isAnimationActive={false} connectNulls />}
            <ReferenceLine x={now.date} stroke={colors.tickFillSecondary} strokeDasharray="3 3" />
            {/* Labels pile up at phone width; the lines alone still mark the races */}
            {raceLines(!isMobile)}
          </ComposedChart>
        </ResponsiveContainer>
      </ChartPanel>

      <ChartPanel
        title="Form" sublabel="% of fitness" glow={false}
        legend={<>
          {FORM_ZONES.map(z => <LegendSwatch key={z.label} color={z.color} label={z.label} />)}
        </>}
      >
        <ResponsiveContainer width="100%" height={170}>
          <ComposedChart data={rows} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
            {FORM_ZONES.map(z => (
              <ReferenceArea key={z.label} y1={z.from} y2={z.to} fill={z.color} fillOpacity={0.07} stroke="none" ifOverflow="hidden" />
            ))}
            <XAxis {...xAxis} />
            <YAxis domain={FORM_DOMAIN} ticks={[-30, -10, 20]} tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
              tickFormatter={(v: number) => `${v}%`} interval={0} width={isMobile ? 32 : 40} axisLine={false} tickLine={false} allowDataOverflow />
            <Tooltip {...colors.tooltip} labelFormatter={tooltipLabel}
              formatter={(v: unknown, name) => {
                if (v == null) return ['–', name]
                const pct = Number(v)
                return [`${pct > 0 ? '+' : ''}${Math.round(pct)}% · ${formZone(pct).label}`, name]
              }} />
            <ReferenceLine y={0} stroke={colors.gridStroke} />
            {/* Neutral line: the zone bands behind it carry the meaning */}
            <Line dataKey="form" name="Form" stroke={colors.tickFill} strokeWidth={1.5} dot={false} isAnimationActive={false} />
            <Line dataKey="formPlan" name="Form (planned)" stroke={colors.tickFill} strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            <ReferenceLine x={now.date} stroke={colors.tickFillSecondary} strokeDasharray="3 3" />
            {raceLines(false)}
          </ComposedChart>
        </ResponsiveContainer>
      </ChartPanel>

      <p className={clsx('text-[11px] text-gray-500 max-w-3xl')}>
        Load is heart-rate based (TRIMP) for every activity with heart rate. Fitness and fatigue are its {data.fitness_days ?? 42}- and {data.fatigue_days ?? 7}-day
        averages, and form is the gap between them. Planned sessions are costed from your own sessions of the last six months.
      </p>
    </section>
  )
}
