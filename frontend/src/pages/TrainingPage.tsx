import { useState, useMemo } from 'react'
import {
  useRacePredictions, useFitnessChart, useFitnessTrend, useEfficiencyFactor, useStreaks,
} from '../api/hooks'
import StatCard from '../components/shared/StatCard'
import {
  ComposedChart, Bar, Line, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Scatter,
} from 'recharts'
import { useTheme } from '../hooks/useTheme'
import { formatPrPace } from '../utils/formatSpeed'
import Methodology from '../components/shared/Formula'
import clsx from 'clsx'

const SPORT_CATEGORIES = [
  { value: 'running', label: 'Running', sportType: 'Run' },
  { value: 'cycling', label: 'Cycling', sportType: 'Ride' },
  { value: 'swimming', label: 'Swimming', sportType: 'Swim' },
]

const PMC_RANGES = [
  { label: '3m', days: 90 },
  { label: '6m', days: 180 },
  { label: '1y', days: 365 },
  { label: 'All', days: 0 },
]

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.round(seconds % 60)
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m}:${s.toString().padStart(2, '0')}`
}

// ── TSB interpretation ────────────────────────
interface FitnessStatus {
  label: string
  description: string
  color: string
  bgClass: string
  textClass: string
}

function getTsbStatus(tsb: number): FitnessStatus {
  if (tsb > 15) return {
    label: 'Race Ready',
    description: 'Well rested — peak performance window',
    color: '#22c55e',
    bgClass: 'bg-green-500/12',
    textClass: 'text-green-400',
  }
  if (tsb > 5) return {
    label: 'Fresh',
    description: 'Good recovery — can push harder',
    color: '#2dd4bf',
    bgClass: 'bg-teal-500/12',
    textClass: 'text-teal-400',
  }
  if (tsb > -10) return {
    label: 'Balanced',
    description: 'Optimal training zone — keep going',
    color: '#60a5fa',
    bgClass: 'bg-blue-500/12',
    textClass: 'text-blue-400',
  }
  if (tsb > -30) return {
    label: 'Fatigued',
    description: 'Accumulating load — building fitness',
    color: '#fb923c',
    bgClass: 'bg-orange-500/12',
    textClass: 'text-orange-400',
  }
  return {
    label: 'Overreached',
    description: 'Need recovery — ease off training',
    color: '#f87171',
    bgClass: 'bg-red-500/12',
    textClass: 'text-red-400',
  }
}

function getLightTsbStatus(tsb: number): FitnessStatus {
  if (tsb > 15) return {
    label: 'Race Ready',
    description: 'Well rested — peak performance window',
    color: '#16a34a',
    bgClass: 'bg-green-100',
    textClass: 'text-green-700',
  }
  if (tsb > 5) return {
    label: 'Fresh',
    description: 'Good recovery — can push harder',
    color: '#0d9488',
    bgClass: 'bg-teal-100',
    textClass: 'text-teal-700',
  }
  if (tsb > -10) return {
    label: 'Balanced',
    description: 'Optimal training zone — keep going',
    color: '#2563eb',
    bgClass: 'bg-blue-100',
    textClass: 'text-blue-700',
  }
  if (tsb > -30) return {
    label: 'Fatigued',
    description: 'Accumulating load — building fitness',
    color: '#ea580c',
    bgClass: 'bg-orange-100',
    textClass: 'text-orange-700',
  }
  return {
    label: 'Overreached',
    description: 'Need recovery — ease off training',
    color: '#dc2626',
    bgClass: 'bg-red-100',
    textClass: 'text-red-700',
  }
}

const MODEL_DESCRIPTIONS: Record<string, string> = {
  riegel: 'Riegel (standard)',
  personalized_riegel: 'Personalized Riegel',
  vdot: 'VDOT (Jack Daniels)',
}

export default function TrainingPage() {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const [sportCategory, setSportCategory] = useState('running')
  const [pmcRange, setPmcRange] = useState(365)

  const sportConfig = SPORT_CATEGORIES.find(s => s.value === sportCategory)!
  const isRunning = sportCategory === 'running'

  // Date range for PMC
  const pmcDates = useMemo(() => {
    if (pmcRange === 0) return { start: undefined, end: undefined }
    const end = new Date().toISOString().slice(0, 10)
    const start = new Date(Date.now() - pmcRange * 86400000).toISOString().slice(0, 10)
    return { start, end }
  }, [pmcRange])

  const { data: predictions, isLoading: predictionsLoading } = useRacePredictions(sportCategory)
  const { data: pmcData, isLoading: pmcLoading } = useFitnessChart(pmcDates.start, pmcDates.end)
  const { data: trendData, isLoading: trendLoading } = useFitnessTrend(sportConfig.sportType)
  const { data: efData } = useEfficiencyFactor(sportConfig.sportType, 28)
  const { data: streakData } = useStreaks()

  const cardClass = clsx(
    'rounded-xl p-4 border chart-card',
    isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
  )

  // ── Derived fitness metrics ──────────────────
  const currentTsb = pmcData?.current?.tsb ?? null
  const currentCtl = pmcData?.current?.ctl ?? null
  const currentAtl = pmcData?.current?.atl ?? null
  const peakCtl = pmcData?.peak_fitness?.ctl ?? null
  const peakCtlDate = pmcData?.peak_fitness?.date
  const fitnessPercent = currentCtl && peakCtl && peakCtl > 0 ? Math.round((currentCtl / peakCtl) * 100) : null
  const status = currentTsb !== null ? (isLight ? getLightTsbStatus(currentTsb) : getTsbStatus(currentTsb)) : null

  // Latest EF value and trend
  const efLatest = efData?.data?.length > 0 ? efData.data[efData.data.length - 1] : null
  const efFirst = efData?.data?.length > 10 ? efData.data[0] : null
  const efTrend = efLatest?.ef_rolling && efFirst?.ef_rolling
    ? ((efLatest.ef_rolling - efFirst.ef_rolling) / efFirst.ef_rolling * 100)
    : null

  // Sample PMC data for chart
  const pmcChartData = useMemo(() => {
    if (!pmcData?.data) return []
    const raw = pmcData.data
    if (raw.length <= 200) return raw
    const step = Math.max(1, Math.floor(raw.length / 200))
    return raw.filter((_: unknown, i: number) => i % step === 0 || i === raw.length - 1)
  }, [pmcData])

  // Top race predictions (limit to most relevant distances)
  const topPredictions = useMemo(() => {
    if (!predictions?.predictions) return []
    return predictions.predictions.filter((p: any) => p.predicted_time_s)
  }, [predictions])

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="page-title">Training</h2>
        <select value={sportCategory} onChange={e => setSportCategory(e.target.value)} className="select">
          {SPORT_CATEGORIES.map(s => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
      </div>

      {/* ═══════ SECTION 1: HOW ARE YOU DOING ═══════ */}
      {pmcLoading ? (
        <div className={clsx(cardClass, 'animate-pulse h-36')} />
      ) : status && currentCtl !== null ? (
        <div className={clsx(
          'rounded-xl border p-5 relative overflow-hidden',
          isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
        )}>
          <div
            className="absolute inset-0 pointer-events-none"
            style={{ background: `radial-gradient(ellipse at top left, ${status.color}08, transparent 60%)` }}
          />

          <div className="relative flex flex-col md:flex-row md:items-center gap-5">
            {/* Recovery status — answers "should I train hard or rest?" */}
            <div className="flex items-center gap-4 md:min-w-[220px]">
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center shrink-0"
                style={{ backgroundColor: `${status.color}15`, border: `1px solid ${status.color}30` }}
              >
                <span className="text-lg font-bold font-mono" style={{ color: status.color }}>
                  {Math.round(currentTsb!)}
                </span>
              </div>
              <div>
                <div className="text-lg font-bold" style={{ color: status.color }}>{status.label}</div>
                <div className={clsx('text-xs', isLight ? 'text-gray-500' : 'text-gray-500')}>{status.description}</div>
              </div>
            </div>

            <div className={clsx('hidden md:block w-px h-12 shrink-0', isLight ? 'bg-gray-200' : 'bg-surface-600')} />

            {/* Just 3 things: how fit vs your best, how tired, consistency */}
            <div className="flex-1 grid grid-cols-3 gap-4">
              {/* How fit compared to your best */}
              <div>
                <div className={clsx('text-[11px] uppercase tracking-wider mb-1', isLight ? 'text-gray-500' : 'text-gray-500')}>
                  Shape vs your best
                </div>
                {fitnessPercent !== null ? (
                  <>
                    <div className="text-xl font-bold font-mono text-blue-400">{fitnessPercent}%</div>
                    {/* Mini progress bar */}
                    <div className={clsx('h-1.5 rounded-full mt-1.5 w-full', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
                      <div
                        className="h-full rounded-full bg-blue-400 transition-all duration-500"
                        style={{ width: `${Math.min(fitnessPercent, 100)}%` }}
                      />
                    </div>
                  </>
                ) : (
                  <div className="text-xl font-bold font-mono text-gray-500">—</div>
                )}
              </div>

              {/* How tired you are */}
              <div>
                <div className={clsx('text-[11px] uppercase tracking-wider mb-1', isLight ? 'text-gray-500' : 'text-gray-500')}>
                  Recent load
                </div>
                <div className="text-xl font-bold font-mono text-red-400">{Math.round(currentAtl ?? 0)}</div>
                <div className={clsx('text-[11px]', isLight ? 'text-gray-500' : 'text-gray-500')}>
                  {currentAtl && currentCtl
                    ? currentAtl > currentCtl ? 'pushing hard' : 'well managed'
                    : ''}
                </div>
              </div>

              {/* Consistency */}
              <div>
                <div className={clsx('text-[11px] uppercase tracking-wider mb-1', isLight ? 'text-gray-500' : 'text-gray-500')}>
                  Consistency
                </div>
                <div className="text-xl font-bold font-mono">{streakData?.current_streak ?? 0}<span className="text-sm ml-0.5 text-gray-500">days</span></div>
                <div className={clsx('text-[11px]', isLight ? 'text-gray-500' : 'text-gray-500')}>
                  record: {streakData?.longest_streak ?? 0} days
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* ═══════ SECTION 2: RACE PREDICTIONS ═══════ */}
      <section>
        <div className="mb-3">
          <div className="flex items-center gap-2">
            <h3 className={clsx('text-sm font-semibold', isLight ? 'text-gray-800' : 'text-gray-100')}>
              What you can {sportCategory === 'running' ? 'run' : sportCategory === 'cycling' ? 'ride' : 'swim'}
            </h3>
            {predictions?.confidence && (
              <span className={clsx(
                'text-[10px] px-1.5 py-0.5 rounded-full font-medium',
                predictions.confidence === 'high' ? (isLight ? 'bg-green-100 text-green-700' : 'bg-green-500/15 text-green-400') :
                predictions.confidence === 'medium' ? (isLight ? 'bg-yellow-100 text-yellow-700' : 'bg-yellow-500/15 text-yellow-400') :
                (isLight ? 'bg-red-100 text-red-700' : 'bg-red-500/15 text-red-400'),
              )}>
                {predictions.confidence} confidence
              </span>
            )}
          </div>
          <Methodology
            tex="t_{\text{predicted}} = t_{\text{known}} \times \left(\frac{d_{\text{new}}}{d_{\text{known}}}\right)^{1.06}"
            description={`We look at your best times at each distance and extrapolate what you could do at others. If you ran 5K in 25 min, we can estimate your 10K or half marathon.${isRunning ? " Uses both Riegel's formula and Jack Daniels' VDOT tables." : ""} Recent results count much more than old ones — a PR from 6+ months ago has very little weight.`}
            accent="#fb923c"
          />
        </div>

        {predictionsLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger-children">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className={clsx(cardClass, 'animate-pulse h-24')} />
            ))}
          </div>
        ) : topPredictions.length > 0 ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger-children">
            {topPredictions.map((p: any) => {
              const modelKeys = Object.keys(p.models ?? {})
              const modelTooltip = modelKeys.map(k =>
                `${MODEL_DESCRIPTIONS[k] ?? k}: ${formatTime(p.models[k])}`
              ).join(' / ')
              return (
                <div
                  key={p.distance_m}
                  className={clsx(
                    'rounded-xl border p-4 card-glow',
                    isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
                  )}
                  style={{ '--card-accent': '#fb923c' } as React.CSSProperties}
                  title={modelTooltip}
                >
                  <div className="text-orange-400 text-xs font-semibold mb-1">{p.label}</div>
                  <div className={clsx('text-2xl font-bold font-mono tracking-tight', isLight ? 'text-gray-900' : 'text-gray-100')}>
                    {formatTime(p.predicted_time_s)}
                  </div>
                  <div className="text-[11px] text-gray-500 font-mono mt-0.5">
                    {formatPrPace(p.predicted_time_s, p.distance_m, sportCategory)}
                  </div>
                </div>
              )
            })}
          </div>
        ) : predictions ? (
          <div className={clsx(cardClass, 'text-center py-6')}>
            <p className="text-sm text-gray-500">Not enough data for predictions. Sync activities with GPS streams.</p>
          </div>
        ) : null}

        {/* Data quality warnings */}
        {predictions?.data_quality?.warnings?.map((w: string, i: number) => (
          <div key={i} className={clsx(
            'text-xs px-3 py-2 rounded-lg mt-3',
            isLight ? 'bg-amber-50 text-amber-700 border border-amber-200' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20',
          )}>
            {w}
          </div>
        ))}
      </section>

      {/* ═══════ SECTION 3: HOW YOUR FITNESS CHANGED OVER TIME ═══════ */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className={clsx('text-sm font-semibold', isLight ? 'text-gray-800' : 'text-gray-100')}>
              Fitness over time
            </h3>
            <Methodology
              tex="\text{TRIMP} = \text{duration} \times \Delta\text{HR} \times e^{1.92 \,\times\, \Delta\text{HR}} \qquad \text{Fitness} = \text{EMA}_{42d} \qquad \text{Fatigue} = \text{EMA}_{7d}"
              description="Each workout gets a training score based on how hard your heart worked and for how long — a tough 1-hour run scores much higher than an easy 30-min jog. The blue line averages that score over ~6 weeks (your fitness), the red line over ~7 days (your recent fatigue). When blue is above red, you're fresh."
              accent="#60a5fa"
            />
          </div>
          <div className="flex items-center gap-0.5 shrink-0 ml-4">
            {PMC_RANGES.map(r => (
              <button
                key={r.label}
                onClick={() => setPmcRange(r.days)}
                className="chip font-mono"
                data-active={pmcRange === r.days}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {pmcLoading ? (
          <div className={clsx(cardClass, 'animate-pulse h-80')} />
        ) : pmcChartData.length > 0 ? (
          <div className={cardClass} style={{ '--card-accent': '#60a5fa' } as React.CSSProperties}>
            {/* Summary row */}
            <div className="flex items-center gap-3 mb-4">
              <div className="grid grid-cols-3 gap-3 flex-1">
                <div className={clsx('rounded-lg px-3 py-2', isLight ? 'bg-gray-50' : 'bg-surface-700/50')}>
                  <div className="text-[10px] uppercase text-gray-500">Your best shape ever</div>
                  <div className="text-sm font-bold font-mono text-blue-400">
                    {peakCtl ? Math.round(peakCtl) : '—'}
                  </div>
                  {peakCtlDate && (
                    <div className="text-[10px] text-gray-500">
                      {new Date(peakCtlDate).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' })}
                    </div>
                  )}
                </div>
                <div className={clsx('rounded-lg px-3 py-2', isLight ? 'bg-gray-50' : 'bg-surface-700/50')}>
                  <div className="text-[10px] uppercase text-gray-500">Current shape</div>
                  <div className="text-sm font-bold font-mono text-blue-400">
                    {currentCtl !== null ? Math.round(currentCtl) : '—'}
                  </div>
                  {fitnessPercent !== null && (
                    <div className="text-[10px] text-gray-500">{fitnessPercent}% of your best</div>
                  )}
                </div>
                <div className={clsx('rounded-lg px-3 py-2', isLight ? 'bg-gray-50' : 'bg-surface-700/50')}>
                  <div className="text-[10px] uppercase text-gray-500">Recovery</div>
                  <div className="text-sm font-bold font-mono" style={{ color: status?.color }}>
                    {status?.label ?? '—'}
                  </div>
                  <div className="text-[10px] text-gray-500">
                    {currentTsb !== null && currentTsb > 5 ? 'ready to push' : currentTsb !== null && currentTsb > -10 ? 'good to train' : 'take it easy'}
                  </div>
                </div>
              </div>
            </div>

            {/* Legend */}
            <div className="flex items-center gap-4 mb-2">
              <div className="flex items-center gap-1.5">
                <span className="w-3 h-0.5 rounded-sm bg-blue-400" />
                <span className="text-[11px] text-gray-500">Long-term fitness</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-3 h-0.5 rounded-sm bg-red-400" />
                <span className="text-[11px] text-gray-500">Recent fatigue</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className={clsx('w-3 h-2 rounded-sm', isLight ? 'bg-orange-200' : 'bg-orange-400/20')} />
                <span className="text-[11px] text-gray-500">Training effort</span>
              </div>
            </div>

            {/* Chart */}
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={pmcChartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="ctlGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#60a5fa" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="#60a5fa" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: colors.tickFill, fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                  interval="equidistantPreserveStart"
                  angle={-45}
                  textAnchor="end"
                  height={55}
                  dy={12}
                />
                <YAxis tick={{ fill: colors.tickFillSecondary, fontSize: 10 }} axisLine={false} tickLine={false} width={40} />
                <Tooltip
                  contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: colors.labelColor }}
                  labelFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                  formatter={(value: any, name: string) => {
                    const labels: Record<string, string> = { ctl: 'Fitness (CTL)', atl: 'Fatigue (ATL)', trimp: 'TRIMP' }
                    return [Number(value).toFixed(1), labels[name] ?? name]
                  }}
                />
                <Bar dataKey="trimp" fill="#fb923c" fillOpacity={0.15} radius={[2, 2, 0, 0]} />
                <Area type="monotone" dataKey="ctl" stroke="#60a5fa" strokeWidth={2} fill="url(#ctlGrad)" dot={false} />
                <Line type="monotone" dataKey="atl" stroke="#f87171" strokeWidth={1.5} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className={clsx(cardClass, 'text-center py-8')}>
            <p className="text-sm text-gray-500">No heart rate data available. Activities with HR data are needed for fitness tracking.</p>
          </div>
        )}

        {/* Data quality warnings */}
        {pmcData?.data_quality?.warnings?.map((w: string, i: number) => (
          <div key={i} className={clsx(
            'text-xs px-3 py-2 rounded-lg mt-3',
            isLight ? 'bg-amber-50 text-amber-700 border border-amber-200' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20',
          )}>
            {w}
          </div>
        ))}
      </section>

      {/* ═══════ SECTION 4: ARE YOU GETTING FASTER (running only) ═══════ */}
      {isRunning && (
        <section>
          <div className="mb-3">
            <div className="flex items-center gap-2">
              <h3 className={clsx('text-sm font-semibold', isLight ? 'text-gray-800' : 'text-gray-100')}>
                Are you getting faster?
              </h3>
              {trendData?.trend && (
                <span className={clsx(
                  'text-[10px] px-1.5 py-0.5 rounded-full font-medium',
                  trendData.trend === 'improving' ? (isLight ? 'bg-green-100 text-green-700' : 'bg-green-500/15 text-green-400') :
                  trendData.trend === 'declining' ? (isLight ? 'bg-red-100 text-red-700' : 'bg-red-500/15 text-red-400') :
                  (isLight ? 'bg-gray-100 text-gray-600' : 'bg-gray-500/15 text-gray-400'),
                )}>
                  {trendData.trend}
                </span>
              )}
            </div>
            <Methodology
              tex="\text{VDOT} = \frac{\text{oxygen cost}(v)}{\text{sustainable } \%\dot{V}O_2\text{max}(t)} \quad \text{where } v = \tfrac{\text{distance}}{\text{time}}"
              description="Each run gets a score that estimates how strong your aerobic engine is. It divides the energy cost of your pace by how long you can sustain that intensity — so it accounts for the fact that you naturally slow down over longer distances. A fast 5K can score higher than a slow ultramarathon. Important: easy recovery jogs will score lower than tempo runs or races, which makes the dots noisy. That's why the 28-day average line matters more than individual dots — it smooths out the mix of hard and easy days."
              accent="#34d399"
            />
          </div>

          {trendLoading ? (
            <div className={clsx(cardClass, 'animate-pulse h-72')} />
          ) : trendData?.activities?.length > 0 ? (
            <div className={cardClass} style={{ '--card-accent': '#34d399' } as React.CSSProperties}>
              {/* Summary */}
              <div className="flex items-center gap-3 mb-4">
                <div className="grid grid-cols-3 gap-3 flex-1">
                  <div className={clsx('rounded-lg px-3 py-2', isLight ? 'bg-gray-50' : 'bg-surface-700/50')}>
                    <div className="text-[10px] uppercase text-gray-500">Running level now</div>
                    <div className="text-sm font-bold font-mono text-emerald-400">{trendData.current_vdot ?? '—'}</div>
                    <div className="text-[10px] text-gray-500">VDOT score</div>
                  </div>
                  {trendData.peak_vdot && (
                    <div className={clsx('rounded-lg px-3 py-2', isLight ? 'bg-gray-50' : 'bg-surface-700/50')}>
                      <div className="text-[10px] uppercase text-gray-500">Your best ever</div>
                      <div className="text-sm font-bold font-mono text-emerald-400">{trendData.peak_vdot.vdot}</div>
                      {trendData.peak_vdot.date && (
                        <div className="text-[10px] text-gray-500">{new Date(trendData.peak_vdot.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' })}</div>
                      )}
                    </div>
                  )}
                  <div className={clsx('rounded-lg px-3 py-2', isLight ? 'bg-gray-50' : 'bg-surface-700/50')}>
                    <div className="text-[10px] uppercase text-gray-500">Based on</div>
                    <div className="text-sm font-bold font-mono">{trendData.data_quality?.activities_with_vdot ?? 0}</div>
                    <div className="text-[10px] text-gray-500">runs analyzed</div>
                  </div>
                </div>
              </div>

              {/* Legend */}
              <div className="flex items-center gap-4 mb-2">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 opacity-40" />
                  <span className="text-[11px] text-gray-500">Each run</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-0.5 rounded-sm bg-emerald-400" />
                  <span className="text-[11px] text-gray-500">Monthly trend</span>
                </div>
                <div className={clsx('text-[11px] ml-auto', isLight ? 'text-gray-400' : 'text-gray-500')}>
                  Higher = faster runner
                </div>
              </div>

              {/* Chart */}
              <ResponsiveContainer width="100%" height={280}>
                <ComposedChart margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
                  <XAxis
                    dataKey="date"
                    type="category"
                    data={trendData.rolling_avg}
                    tick={{ fill: colors.tickFill, fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { month: 'short', year: '2-digit' })}
                    interval="equidistantPreserveStart"
                    allowDuplicatedCategory={false}
                    angle={-45}
                    textAnchor="end"
                    height={55}
                    dy={12}
                  />
                  <YAxis
                    tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    width={40}
                    domain={['auto', 'auto']}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: colors.labelColor }}
                    labelFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                  />
                  <Scatter
                    data={trendData.activities}
                    dataKey="vdot"
                    fill="#34d399"
                    fillOpacity={0.3}
                    r={3}
                    name="VDOT"
                  />
                  <Line
                    data={trendData.rolling_avg}
                    dataKey="vdot"
                    stroke="#34d399"
                    strokeWidth={2.5}
                    dot={false}
                    type="monotone"
                    name="28d Avg"
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : trendData ? (
            <div className={clsx(cardClass, 'text-center py-8')}>
              <p className="text-sm text-gray-500">Not enough running activities to compute VDOT trend.</p>
            </div>
          ) : null}
        </section>
      )}

      {/* ═══════ SECTION 5: ARE YOU GETTING MORE EFFICIENT ═══════ */}
      {efData?.data?.length > 5 && (
        <section>
          <div className="mb-3">
            <h3 className={clsx('text-sm font-semibold', isLight ? 'text-gray-800' : 'text-gray-100')}>
              Are you getting more efficient?
            </h3>
            <Methodology
              tex="\text{Efficiency} = \frac{\text{speed (m/s)}}{\text{avg heart rate (bpm)}}"
              description="For each activity, we divide your speed by your average heart rate. If you ran 10 km/h at 150 bpm last month, and now you do the same pace at 140 bpm, this number goes up — you're producing the same speed with less cardiac effort. That's real aerobic improvement."
              accent="#a78bfa"
            />
          </div>

          <div className={cardClass} style={{ '--card-accent': '#a78bfa' } as React.CSSProperties}>
            <div className="flex items-center gap-4 mb-2">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-violet-400 opacity-40" />
                <span className="text-[11px] text-gray-500">Per activity</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-3 h-0.5 rounded-sm bg-violet-400" />
                <span className="text-[11px] text-gray-500">28-day avg</span>
              </div>
              <div className={clsx('text-[11px] ml-auto', isLight ? 'text-gray-400' : 'text-gray-500')}>
                Line going up = you're improving
              </div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <ComposedChart data={efData.data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: colors.tickFill, fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                  interval="equidistantPreserveStart"
                  angle={-45}
                  textAnchor="end"
                  height={50}
                  dy={10}
                />
                <YAxis
                  tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  width={45}
                  tickFormatter={(v: number) => v.toFixed(3)}
                  domain={['auto', 'auto']}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: colors.labelColor }}
                  labelFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                  formatter={(value: any, name: string) => {
                    const labels: Record<string, string> = { ef: 'EF', ef_rolling: '28d Avg' }
                    return [Number(value).toFixed(4), labels[name] ?? name]
                  }}
                />
                <Scatter dataKey="ef" fill="#a78bfa" fillOpacity={0.25} r={2.5} name="EF" />
                <Line type="monotone" dataKey="ef_rolling" stroke="#a78bfa" strokeWidth={2.5} dot={false} name="28d Avg" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}
    </div>
  )
}
