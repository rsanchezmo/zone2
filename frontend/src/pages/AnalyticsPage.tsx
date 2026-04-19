import { useMemo, useState } from 'react'
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { useRacePredictions, useRacePredictionsHistory } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { formatSpeed } from '../utils/formatSpeed'
import { useTheme } from '../hooks/useTheme'
import clsx from 'clsx'

const SPORTS: { key: string; label: string; sportType: string }[] = [
  { key: 'running', label: 'Running', sportType: 'Run' },
  { key: 'cycling', label: 'Cycling', sportType: 'Ride' },
  { key: 'swimming', label: 'Swimming', sportType: 'Swim' },
]

interface PredictionEntry {
  distance_m: number
  label: string
  pr_time_s: number | null
  pr_date: string | null
  source: string
  predicted_time_s: number | null
  predicted_time_low_s: number | null
  predicted_time_high_s: number | null
  models: Record<string, number | null>
}

function formatSec(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return '—'
  const total = Math.round(s)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const sec = total % 60
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
  return `${m}:${sec.toString().padStart(2, '0')}`
}

export default function AnalyticsPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [sport, setSport] = useState<string>('running')
  const [weeks, setWeeks] = useState<number>(52)
  const sportMeta = SPORTS.find(s => s.key === sport) ?? SPORTS[0]
  const accent = getSportColor(sportMeta.sportType)

  const { data: preds, isLoading: predsLoading } = useRacePredictions(sport)
  const { data: history, isLoading: histLoading } = useRacePredictionsHistory(sport, weeks)

  const predictions: PredictionEntry[] = preds?.predictions ?? []
  const validPredictions = predictions.filter(p => p.predicted_time_s != null)

  const [focusDistance, setFocusDistance] = useState<number | null>(null)
  const effectiveFocus = useMemo(() => {
    if (focusDistance != null && validPredictions.some(p => p.distance_m === focusDistance)) {
      return focusDistance
    }
    return validPredictions[0]?.distance_m ?? null
  }, [focusDistance, validPredictions])
  const focusedLabel = useMemo(
    () => validPredictions.find(p => p.distance_m === effectiveFocus)?.label ?? '',
    [validPredictions, effectiveFocus],
  )

  const chartData = useMemo(() => {
    if (!history?.points || effectiveFocus == null) return []
    return (history.points as Array<{ end_date: string; predictions: PredictionEntry[] }>)
      .map(point => {
        const p = point.predictions.find(pp => pp.distance_m === effectiveFocus)
        if (!p || p.predicted_time_s == null) return null
        const low = p.predicted_time_low_s ?? p.predicted_time_s
        const high = p.predicted_time_high_s ?? p.predicted_time_s
        return {
          date: point.end_date,
          time: p.predicted_time_s,
          low,
          high,
          band: high - low,  // stacked atop low to paint the IQR band
        }
      })
      .filter((x): x is NonNullable<typeof x> => x != null)
  }, [history, effectiveFocus])

  const yDomain = useMemo<[number, number]>(() => {
    if (!chartData.length) return [0, 0]
    const vals = chartData.flatMap(d => [d.low, d.high, d.time])
    const min = Math.min(...vals)
    const max = Math.max(...vals)
    const pad = Math.max((max - min) * 0.15, 5)
    return [Math.max(0, min - pad), max + pad]
  }, [chartData])

  const panelClass = clsx(
    'panel',
    isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
  )

  return (
    <div className="max-w-5xl mx-auto space-y-8 pb-12">
      {/* Header */}
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-baseline gap-2">
          <span
            className="eyebrow"
            style={{ borderLeftWidth: 2, borderLeftColor: accent, paddingLeft: 8 }}
          >
            Analytics
          </span>
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {SPORTS.map(s => {
            const c = getSportColor(s.sportType)
            const active = s.key === sport
            return (
              <button
                key={s.key}
                onClick={() => { setSport(s.key); setFocusDistance(null) }}
                className="text-[11px] uppercase tracking-[0.15em] px-3 py-1.5 rounded-full border font-semibold transition-colors"
                style={{
                  color: active ? c : undefined,
                  borderColor: active ? `${c}50` : undefined,
                  backgroundColor: active ? `${c}15` : 'transparent',
                }}
              >
                {s.label}
              </button>
            )
          })}
        </div>
      </header>

      {/* Race predictions block */}
      <section className={clsx(panelClass, 'p-5 md:p-6 space-y-4')}>
        <div className="flex items-baseline justify-between flex-wrap gap-2">
          <span
            className="eyebrow"
            style={{ borderLeftWidth: 2, borderLeftColor: accent, paddingLeft: 8, color: accent }}
          >
            Race predictor
          </span>
          {preds?.confidence && (
            <span className={clsx(
              'text-[10px] uppercase tracking-[0.15em] font-semibold px-2 py-0.5 rounded-full border',
              preds.confidence === 'high' && 'text-emerald-400 border-emerald-400/40',
              preds.confidence === 'medium' && 'text-amber-400 border-amber-400/40',
              preds.confidence === 'low' && 'text-rose-400 border-rose-400/40',
            )}>
              {preds.confidence} confidence
            </span>
          )}
        </div>

        {predsLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className={clsx('p-3 rounded-lg border animate-pulse h-24', isLight ? 'bg-gray-50 border-gray-200' : 'bg-surface-700/50 border-surface-600')} />
            ))}
          </div>
        ) : validPredictions.length === 0 ? (
          <div className="py-8 text-center text-sm text-gray-500">
            {preds?.data_quality?.warnings?.[0] ?? 'No recent data to predict from.'}
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {validPredictions.map(p => {
              const isFocused = p.distance_m === effectiveFocus
              const isRecent = p.source === 'personal_record' && p.pr_time_s != null
              const band = (p.predicted_time_high_s != null && p.predicted_time_low_s != null)
                ? `${formatSec(p.predicted_time_low_s)} – ${formatSec(p.predicted_time_high_s)}`
                : null
              return (
                <button
                  key={p.distance_m}
                  onClick={() => setFocusDistance(p.distance_m)}
                  className={clsx(
                    'text-left p-3 rounded-lg border transition-colors',
                    isLight ? 'bg-gray-50 border-gray-200 hover:bg-gray-100' : 'bg-surface-700/50 border-surface-600 hover:bg-surface-700',
                  )}
                  style={isFocused ? {
                    borderColor: `${accent}80`,
                    backgroundColor: `${accent}12`,
                  } : undefined}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="eyebrow" style={{ color: isFocused ? accent : undefined }}>{p.label}</span>
                    <span
                      className={clsx(
                        'text-[8.5px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded-full border whitespace-nowrap',
                        isRecent ? 'border-current' : isLight ? 'text-gray-400 border-gray-300' : 'text-gray-500 border-surface-500',
                      )}
                      style={isRecent ? { color: accent, borderColor: `${accent}60`, backgroundColor: `${accent}15` } : undefined}
                    >
                      {isRecent ? 'Anchored' : 'Estimation'}
                    </span>
                  </div>
                  <div className={clsx('text-xl md:text-2xl font-bold font-mono tabular-nums', isLight ? 'text-gray-900' : 'text-gray-100')}>
                    {formatSec(p.predicted_time_s)}
                  </div>
                  {p.predicted_time_s != null && p.predicted_time_s > 0 && (
                    <div className={clsx('text-[11px] font-mono tabular-nums mt-0.5', isLight ? 'text-gray-600' : 'text-gray-300')}>
                      {formatSpeed(p.distance_m / p.predicted_time_s, sportMeta.sportType)}
                    </div>
                  )}
                  {band && (
                    <div className="text-[10px] text-gray-500 font-mono tabular-nums mt-1">
                      {band}
                    </div>
                  )}
                  {isRecent && p.pr_time_s != null && (
                    <div className="text-[10px] text-gray-500 font-mono tabular-nums mt-0.5">
                      recent best {formatSec(p.pr_time_s)}
                    </div>
                  )}
                </button>
              )
            })}
          </div>
        )}

        {preds?.data_quality?.warnings && preds.data_quality.warnings.length > 0 && (
          <div className="text-[11px] text-amber-400/80 space-y-0.5 pt-1 border-t border-dashed" style={{ borderColor: isLight ? '#e5e7eb' : '#334155' }}>
            {preds.data_quality.warnings.map((w: string, i: number) => (
              <div key={i}>⚠ {w}</div>
            ))}
          </div>
        )}
      </section>

      {/* Evolution chart */}
      <section className={clsx(panelClass, 'p-5 md:p-6 space-y-4')}>
        <div className="flex items-baseline justify-between flex-wrap gap-2">
          <span
            className="eyebrow"
            style={{ borderLeftWidth: 2, borderLeftColor: accent, paddingLeft: 8, color: accent }}
          >
            Evolution — {focusedLabel}
          </span>
          <div className="flex items-center gap-0.5">
            {([12, 16, 24, 52] as const).map(w => (
              <button
                key={w}
                onClick={() => setWeeks(w)}
                className="chip font-mono"
                data-active={weeks === w}
              >
                {w}w
              </button>
            ))}
          </div>
        </div>

        {histLoading ? (
          <div className={clsx('h-[280px] rounded-lg animate-pulse', isLight ? 'bg-gray-100' : 'bg-surface-700/50')} />
        ) : chartData.length === 0 ? (
          <div className="h-[280px] flex items-center justify-center text-sm text-gray-500">
            Not enough historical data to plot evolution.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={chartData} margin={{ top: 8, right: 8, left: 4, bottom: 8 }}>
              <CartesianGrid stroke={isLight ? '#e5e7eb' : '#334155'} strokeDasharray="2 4" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fill: isLight ? '#64748b' : '#94a3b8', fontSize: 10 }}
                tickFormatter={(v: string) => {
                  const d = new Date(v)
                  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' })
                }}
                interval={chartData.length <= 16 ? 0 : Math.floor(chartData.length / 12)}
                angle={-45}
                textAnchor="end"
                height={55}
                dy={8}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: isLight ? '#64748b' : '#94a3b8', fontSize: 10 }}
                tickFormatter={(v: number) => formatSec(v)}
                width={60}
                axisLine={false}
                tickLine={false}
                domain={yDomain}
                reversed
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{
                  background: isLight ? '#ffffff' : '#0f172a',
                  border: `1px solid ${isLight ? '#e5e7eb' : '#334155'}`,
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelStyle={{ color: isLight ? '#334155' : '#e2e8f0' }}
                itemStyle={{ color: isLight ? '#334155' : '#e2e8f0' }}
                formatter={(v: number | number[], name: string) => {
                  if (name === 'Central') return [formatSec(v as number), 'Predicted']
                  if (name === 'IQR' && Array.isArray(v)) {
                    return [`${formatSec(v[0])} – ${formatSec(v[1])}`, 'IQR band']
                  }
                  return null
                }}
                labelFormatter={(v: string) => new Date(v).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
              />
              {/* Range Area: dataKey returns [low, high] so Recharts draws the
                  filled band between them directly — no stacking hacks. */}
              <Area
                type="monotone"
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                dataKey={(d: any) => [d.low, d.high]}
                name="IQR"
                stroke="none"
                fill={accent}
                fillOpacity={0.18}
                isAnimationActive={false}
                activeDot={false}
              />
              <Line
                type="monotone"
                dataKey="time"
                name="Central"
                stroke={accent}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: accent }}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </section>
    </div>
  )
}
